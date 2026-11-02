"""Coordinator for polling Sogedo consumption data."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta

from homeassistant.config_entries import ConfigEntry, ConfigEntryAuthFailed
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import BACKFILL_DAYS, DOMAIN, SCAN_INTERVAL_SECONDS, UPDATE_DATE_OFFSET
from .sogedo_api import SogedoAuthError, SogedoClient, select_latest

_LOGGER = logging.getLogger(__name__)

# Dedicated statistics-only statistics owned by this integration. There is no
# live entity behind them, so the recorder never recompiles them and the Energy
# Dashboard reads a clean cumulative series whose deltas are the daily values.
HISTORY_STATISTIC_ID = "sensor.sogedo_water_consumption"
COST_STATISTIC_ID = "sensor.sogedo_water_cost"

# Re-check this many trailing days on every poll: Sogedo publishes late (J-1
# or later), so a day written as a placeholder must be corrected.
HISTORY_REFRESH_DAYS = 7


class SogedoCoordinator(DataUpdateCoordinator[dict]):
    """Fetch and expose Sogedo daily consumption."""

    def __init__(
        self,
        hass: HomeAssistant,
        client: SogedoClient,
        subscription_id: str,
        entry: ConfigEntry,
        persist_token: Callable[[str], Awaitable[None]] | None = None,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name="Sogedo consumption",
            update_interval=timedelta(seconds=SCAN_INTERVAL_SECONDS),
            config_entry=entry,
        )
        self.client = client
        self.subscription_id = subscription_id
        self._persist_token = persist_token
        self._last_token = client.refresh_token
        self._backfilled = False
        self._days: dict[datetime.date, float] = {}
        self._history_last: datetime.date | None = None

    async def _async_update_data(self) -> dict:
        today = dt_util.now().date()
        start = today - timedelta(days=UPDATE_DATE_OFFSET)
        end = today

        try:
            entries = await self.hass.async_add_executor_job(
                self.client.get_daily_consumption,
                self.subscription_id,
                start.isoformat(),
                end.isoformat(),
            )
        except SogedoAuthError as err:
            # Raises ConfigEntryAuthFailed so HA auto-triggers an in-place
            # reauth (entities are preserved). Reauth is handled by the
            # config flow's async_step_reauth.
            raise ConfigEntryAuthFailed(f"Sogedo auth failed: {err}") from err
        except Exception as err:
            raise UpdateFailed(f"Sogedo update failed: {err}") from err

        # Most recent day with a real reading is the target (J-1).
        latest = select_latest(entries)

        data = {
            "daily_consumption": latest["consumptionValue"] if latest else None,
            "cumulative": latest["indexValue"] if latest else None,
            "index_date": latest["indexDate"] if latest else None,
            "available": bool(latest and latest.get("isIndexValueAvailable")),
        }

        if not self._backfilled:
            # Retry on the next poll if the backfill failed.
            self._backfilled = await self._backfill()
        else:
            await self._append_recent(today)

        await self._save_token()
        return data

    async def _save_token(self) -> None:
        """Persist a rotated refresh token so restarts keep the session alive."""
        if self._persist_token is None:
            return
        token = self.client.refresh_token
        if token and token != self._last_token:
            try:
                await self._persist_token(token)
                self._last_token = token
            except Exception:  # noqa: BLE001
                _LOGGER.debug("Could not persist refresh token", exc_info=True)

    async def async_refresh_history(self) -> None:
        """Re-run the full backfill on demand (idempotent upsert)."""
        await self._backfill()

    async def _fetch_range(self, start: datetime.date, end: datetime.date) -> list[dict]:
        entries: list[dict] = []
        cur = start
        while cur <= end:
            chunk_end = min(end, cur + timedelta(days=365))
            chunk = await self.hass.async_add_executor_job(
                self.client.get_daily_consumption,
                self.subscription_id,
                cur.isoformat(),
                chunk_end.isoformat(),
            )
            entries.extend(chunk)
            cur = chunk_end + timedelta(days=1)
        return entries

    async def _get_price(self) -> float | None:
        """Read the water price (EUR/m³) from the Energy Dashboard config."""
        try:
            from homeassistant.components.energy.data import async_get_manager

            manager = await async_get_manager(self.hass)
            prefs = manager.data
            if not prefs:
                return None
            for source in prefs.get("energy_sources", []):
                if (
                    source.get("type") == "water"
                    and source.get("stat_energy_from") == HISTORY_STATISTIC_ID
                ):
                    return source.get("number_energy_price")
        except Exception:  # noqa: BLE001
            _LOGGER.debug("Could not read energy price", exc_info=True)
        return None

    @staticmethod
    def _collect_days(
        entries: list[dict], today: datetime.date
    ) -> list[tuple[datetime.date, float]]:
        days: list[tuple[datetime.date, float]] = []
        for e in entries:
            try:
                d = datetime.fromisoformat(
                    e["indexDate"].replace("Z", "+00:00")
                ).date()
            except (KeyError, ValueError):
                continue
            if d >= today:
                continue
            # Not yet published: Sogedo sends a 0 placeholder, not a real
            # reading. Writing it would freeze the day at zero.
            if not e.get("isIndexValueAvailable"):
                continue
            if e.get("consumptionValue") is None:
                continue
            days.append((d, float(e["consumptionValue"])))
        days.sort()
        return days

    @staticmethod
    def _build_series(
        days: list[tuple[datetime.date, float]], price: float | None
    ) -> tuple[list[dict], list[dict]]:
        """Build cumulative consumption (and cost) statistics from daily values."""
        cons_stats: list[dict] = []
        cost_stats: list[dict] = []
        cons_total = 0.0
        cost_total = 0.0
        for d, value in days:
            cons_total += value
            cons_stats.append(
                {
                    "start": datetime(d.year, d.month, d.day, tzinfo=dt_util.UTC),
                    "state": cons_total,
                    "sum": cons_total,
                }
            )
            if price is not None:
                cost_total += value * price
                cost_stats.append(
                    {
                        "start": datetime(d.year, d.month, d.day, tzinfo=dt_util.UTC),
                        "state": cost_total,
                        "sum": cost_total,
                    }
                )
        return cons_stats, cost_stats

    async def _backfill(self) -> bool:
        """Backfill the full history, replacing daily placeholders.

        Writes running cumulatives of the daily consumption (and cost) as
        `sum`/`state` so the Energy Dashboard's `change` (sum deltas) equals
        each day's consumption / cost. Idempotent: re-running overwrites the
        same rows. Returns False when the fetch failed, so it is retried.
        """
        try:
            today = dt_util.utcnow().date()
            end_date = today - timedelta(days=1)
            start = end_date - timedelta(days=BACKFILL_DAYS)

            entries = await self._fetch_range(start, end_date)
            days = self._collect_days(entries, today)
            if not days:
                return True

            self._days = dict(days)
            count = await self._rewrite_tail(days[0][0])
            _LOGGER.info("Sogedo backfilled %s days of water history", count)
            return True
        except Exception:  # noqa: BLE001
            _LOGGER.warning("Sogedo backfill failed; retrying next poll", exc_info=True)
            return False

    async def _ensure_cost_stat(self) -> None:
        """Point the Energy Dashboard water source's Coût at the cost statistic."""
        try:
            from homeassistant.components.energy.data import async_get_manager

            manager = await async_get_manager(self.hass)
            if manager.data is None:
                return
            sources = list(manager.data.get("energy_sources", []))
            changed = False
            for i, source in enumerate(sources):
                if (
                    source.get("type") == "water"
                    and source.get("stat_energy_from") == HISTORY_STATISTIC_ID
                    and not source.get("stat_cost")
                ):
                    sources[i] = {**source, "stat_cost": COST_STATISTIC_ID}
                    changed = True
            if changed:
                await manager.async_update({"energy_sources": sources})
                _LOGGER.info("Sogedo water source Coût set to %s", COST_STATISTIC_ID)
        except Exception:  # noqa: BLE001
            _LOGGER.debug("Could not set the energy cost statistic", exc_info=True)

    async def async_cleanup_old_statistics(self) -> None:
        """One-time removal of stray statistics written by earlier versions.

        Earlier versions imported rows into the live cumulative sensor's
        statistic_id (and a fallback), producing incoherent history. Clear
        those statistics so the old sensor's history no longer shows jumps.
        """
        try:
            import asyncio

            from homeassistant.components.recorder import get_instance
            from homeassistant.helpers.entity_registry import (
                async_get as async_get_entity_registry,
            )

            stat_ids = {"sensor.sogedo_water_cumulative"}
            registry = async_get_entity_registry(self.hass)
            for entity in registry.entities.values():
                if entity.platform == DOMAIN and entity.unique_id.endswith(
                    "_cumulative"
                ):
                    stat_ids.add(entity.entity_id)

            instance = get_instance(self.hass)
            done = asyncio.Event()
            instance.async_clear_statistics(
                list(stat_ids),
                on_done=lambda: self.hass.loop.call_soon_threadsafe(done.set),
            )
            try:
                async with asyncio.timeout(30):
                    await done.wait()
            except TimeoutError:
                return
            _LOGGER.info(
                "Sogedo cleared stray statistics: %s", ", ".join(sorted(stat_ids))
            )
        except Exception:  # noqa: BLE001
            _LOGGER.debug("Could not clean stray statistics", exc_info=True)

    def _merge_days(self, entries: list[dict], today: datetime.date) -> bool:
        """Record published daily values; return True if any day changed."""
        changed = False
        for d, value in self._collect_days(entries, today):
            if self._days.get(d) != value:
                self._days[d] = value
                changed = True
        return changed

    async def _append_recent(self, today: datetime.date) -> None:
        """Re-check recent days so late-published values replace placeholders."""
        try:
            end = today - timedelta(days=1)
            start = (self._history_last or end) - timedelta(days=HISTORY_REFRESH_DAYS)
            if start > end:
                return

            entries = await self._fetch_range(start, end)
            if not self._merge_days(entries, today):
                return
            if self._history_last is None:
                # No known total to anchor the running sums: redo the full
                # backfill instead of writing a tail that starts at 0.
                await self._backfill()
                return

            count = await self._rewrite_tail(start)
            _LOGGER.info("Sogedo updated %s days of water history", count)
        except Exception:  # noqa: BLE001
            _LOGGER.warning("Sogedo history update failed; skipping", exc_info=True)

    async def _rewrite_tail(self, first_day: datetime.date) -> int:
        """Rewrite statistics from `first_day` on with correct running sums."""
        days = sorted((d, v) for d, v in self._days.items() if d >= first_day)
        if not days:
            return 0

        base = sum(v for d, v in self._days.items() if d < first_day)
        price = await self._get_price()
        cons_stats, cost_stats = self._build_series(days, price)
        for stat in cons_stats:
            stat["state"] += base
            stat["sum"] += base
        for stat in cost_stats:
            stat["state"] += base * price
            stat["sum"] += base * price

        self._write_statistics(cons_stats, HISTORY_STATISTIC_ID, "volume", "m³")
        if cost_stats:
            self._write_statistics(cost_stats, COST_STATISTIC_ID, None, "EUR")
            await self._ensure_cost_stat()

        self._history_last = days[-1][0]
        return len(days)

    def _write_statistics(
        self,
        stats: list[dict],
        statistic_id: str,
        unit_class: str | None,
        unit_of_measurement: str,
    ) -> None:
        from homeassistant.components.recorder.statistics import (
            async_import_statistics,
        )

        meta = {
            "has_mean": False,
            "mean_type": 0,  # StatisticMeanType.NONE
            "has_sum": True,
            "name": "Sogedo water",
            "source": "recorder",
            "statistic_id": statistic_id,
            "unit_class": unit_class,
            "unit_of_measurement": unit_of_measurement,
        }
        async_import_statistics(self.hass, meta, stats)