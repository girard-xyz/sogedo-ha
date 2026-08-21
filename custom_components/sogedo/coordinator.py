"""Coordinator for polling Sogedo consumption data."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

from homeassistant.config_entries import ConfigEntry, ConfigEntryAuthFailed
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import BACKFILL_DAYS, SCAN_INTERVAL_SECONDS, UPDATE_DATE_OFFSET
from .sogedo_api import SogedoAuthError, SogedoClient, select_latest

_LOGGER = logging.getLogger(__name__)

# Dedicated statistics-only statistics owned by this integration. There is no
# live entity behind them, so the recorder never recompiles them and the Energy
# Dashboard reads a clean cumulative series whose deltas are the daily values.
HISTORY_STATISTIC_ID = "sensor.sogedo_water_consumption"
COST_STATISTIC_ID = "sensor.sogedo_water_cost"


class SogedoCoordinator(DataUpdateCoordinator[dict]):
    """Fetch and expose Sogedo daily consumption."""

    def __init__(
        self,
        hass: HomeAssistant,
        client: SogedoClient,
        subscription_id: str,
        entry: ConfigEntry,
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
        self._backfilled = False
        self._history_sum = 0.0
        self._history_cost_sum = 0.0
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
            await self._backfill()
            self._backfilled = True
        else:
            await self._append_recent(today)

        return data

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
        entries: list[dict],
        today: datetime.date,
        min_date: datetime.date | None = None,
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
            if min_date is not None and d <= min_date:
                continue
            if e.get("consumptionValue") is None:
                continue
            days.append((d, float(e["consumptionValue"])))
        days.sort()
        return days

    @staticmethod
    def _build_series(
        days: list[tuple[datetime.date, float]], price: float | None
    ) -> tuple[list[dict], list[dict], float, float]:
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
        return cons_stats, cost_stats, cons_total, cost_total

    async def _backfill(self) -> None:
        """Best-effort backfill of the full history into the recorder.

        Writes running cumulatives of the daily consumption (and cost) as
        `sum`/`state` so the Energy Dashboard's `change` (sum deltas) equals
        each day's consumption / cost. Idempotent: re-running overwrites the
        same rows.
        """
        try:
            price = await self._get_price()
            today = dt_util.utcnow().date()
            end_date = today - timedelta(days=1)
            start = end_date - timedelta(days=BACKFILL_DAYS)

            entries = await self._fetch_range(start, end_date)
            days = self._collect_days(entries, today)
            if not days:
                return

            cons_stats, cost_stats, cons_total, cost_total = self._build_series(
                days, price
            )

            self._write_statistics(cons_stats, HISTORY_STATISTIC_ID, "volume", "m³")
            if cost_stats:
                self._write_statistics(cost_stats, COST_STATISTIC_ID, None, "EUR")

            self._history_sum = cons_total
            self._history_cost_sum = cost_total
            self._history_last = days[-1][0]
            _LOGGER.info("Sogedo backfilled %s days of water history", len(days))
        except Exception:  # noqa: BLE001
            _LOGGER.warning("Sogedo backfill failed; skipping", exc_info=True)

    async def _append_recent(self, today: datetime.date) -> None:
        """Extend the history statistics with any new days since the last run."""
        try:
            if self._history_last is None:
                return
            start = self._history_last
            end = today - timedelta(days=1)
            if start >= end:
                return

            entries = await self._fetch_range(start, end)
            days = self._collect_days(entries, today, min_date=self._history_last)
            if not days:
                return

            price = await self._get_price()
            cons_stats, cost_stats, cons_added, cost_added = self._build_series(
                days, price
            )
            # The series builders start from 0; offset them by the stored totals.
            for stat in cons_stats:
                stat["state"] += self._history_sum
                stat["sum"] += self._history_sum
            for stat in cost_stats:
                stat["state"] += self._history_cost_sum
                stat["sum"] += self._history_cost_sum

            self._write_statistics(cons_stats, HISTORY_STATISTIC_ID, "volume", "m³")
            if cost_stats:
                self._write_statistics(cost_stats, COST_STATISTIC_ID, None, "EUR")

            self._history_sum += cons_added
            self._history_cost_sum += cost_added
            self._history_last = days[-1][0]
            _LOGGER.info("Sogedo appended %s days of water history", len(days))
        except Exception:  # noqa: BLE001
            _LOGGER.warning("Sogedo history append failed; skipping", exc_info=True)

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