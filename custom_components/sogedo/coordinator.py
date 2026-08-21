"""Coordinator for polling Sogedo consumption data."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

from homeassistant.config_entries import ConfigEntry, ConfigEntryAuthFailed
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_registry import async_get as async_get_entity_registry
from homeassistant.util import dt as dt_util
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import BACKFILL_DAYS, SCAN_INTERVAL_SECONDS, UPDATE_DATE_OFFSET
from .sogedo_api import SogedoAuthError, SogedoClient, select_latest

_LOGGER = logging.getLogger(__name__)


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
            await self._backfill(start)
            self._backfilled = True

        return data

    async def async_refresh_history(self) -> None:
        """Re-run the backfill on demand (idempotent upsert)."""
        await self._backfill(dt_util.now().date())

    async def _backfill(self, end_date: datetime.date) -> None:
        """Best-effort backfill of water history into the recorder.

        Fetches in one-year chunks so the full history is pulled regardless of
        any API range limit. Never raises: a failure here must not fail setup.
        """
        try:
            start = end_date - timedelta(days=BACKFILL_DAYS)

            entries: list[dict] = []
            cur = start
            while cur <= end_date:
                chunk_end = min(end_date, cur + timedelta(days=365))
                chunk = await self.hass.async_add_executor_job(
                    self.client.get_daily_consumption,
                    self.subscription_id,
                    cur.isoformat(),
                    chunk_end.isoformat(),
                )
                entries.extend(chunk)
                cur = chunk_end + timedelta(days=1)

            valid = [
                e
                for e in entries
                if e.get("isIndexValueAvailable") and e.get("indexValue") is not None
            ]
            if not valid:
                return

            from homeassistant.components.recorder.statistics import (
                async_import_statistics,
            )

            # The cumulative sensor feeds the Energy Dashboard. HA reads the
            # sensor's own (dot-form) statistic_id, so use the real entity_id
            # via the recorder's internal import path (source "recorder") to
            # merge the backfill with the live statistics.
            statistic_id = self._cumulative_entity_id()
            meta = {
                "has_mean": False,
                "mean_type": 0,  # StatisticMeanType.NONE
                "has_sum": True,
                "name": "Sogedo water",
                "source": "recorder",
                "statistic_id": statistic_id,
                "unit_class": "volume",
                "unit_of_measurement": "m³",
            }
            stats = [
                {
                    "start": datetime.fromisoformat(
                        e["indexDate"].replace("Z", "+00:00")
                    ),
                    "sum": e["indexValue"],
                }
                for e in valid
            ]
            await async_import_statistics(self.hass, meta, stats)
            _LOGGER.info("Sogedo backfilled %s days of water history", len(stats))
        except Exception:  # noqa: BLE001
            _LOGGER.warning("Sogedo backfill failed; skipping", exc_info=True)

    def _cumulative_entity_id(self) -> str:
        """Entity id of the cumulative sensor, localized via the registry."""
        registry = async_get_entity_registry(self.hass)
        entity = next(
            (
                e
                for e in registry.entities.values()
                if e.platform == "sogedo" and e.unique_id.endswith("_cumulative")
            ),
            None,
        )
        return entity.entity_id if entity else "sensor.sogedo_water_cumulative"
