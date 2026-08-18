"""Coordinator for polling Sogedo consumption data."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import BACKFILL_DAYS, DOMAIN, SCAN_INTERVAL_SECONDS, UPDATE_DATE_OFFSET
from .sogedo_api import SogedoClient, select_latest

_LOGGER = logging.getLogger(__name__)


class SogedoCoordinator(DataUpdateCoordinator[dict]):
    """Fetch and expose Sogedo daily consumption."""

    def __init__(
        self,
        hass: HomeAssistant,
        client: SogedoClient,
        subscription_id: str,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name="Sogedo consumption",
            update_interval=timedelta(seconds=SCAN_INTERVAL_SECONDS),
        )
        self.client = client
        self.subscription_id = subscription_id
        self._backfilled = False

    async def _async_update_data(self) -> dict:
        today = datetime.now(self.hass.config.time_zone).date()
        start = today - timedelta(days=UPDATE_DATE_OFFSET)
        end = today

        try:
            entries = await self.hass.async_add_executor_job(
                self.client.get_daily_consumption,
                self.subscription_id,
                start.isoformat(),
                end.isoformat(),
            )
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

    async def _backfill(self, end_date: datetime.date) -> None:
        """Load up to BACKFILL_DAYS of history into the recorder."""
        start = end_date - timedelta(days=BACKFILL_DAYS)
        try:
            entries = await self.hass.async_add_executor_job(
                self.client.get_daily_consumption,
                self.subscription_id,
                start.isoformat(),
                end_date.isoformat(),
            )
        except Exception:  # noqa: BLE001
            _LOGGER.warning("Sogedo backfill failed; skipping", exc_info=True)
            return

        from homeassistant.components.recorder.statistics import (
            async_add_external_statistics,
        )
        from homeassistant.components.recorder.models import StatisticData, StatisticMetaData

        valid = [
            e
            for e in entries
            if e.get("isIndexValueAvailable") and e.get("consumptionValue") is not None
        ]
        if not valid:
            return

        meta = StatisticMetaData(
            has_mean=False,
            has_sum=True,
            name="Sogedo water daily",
            source=DOMAIN,
            statistic_id=f"{DOMAIN}_water_daily",
            unit_of_measurement="m³",
        )
        stats = [
            StatisticData(
                start=datetime.fromisoformat(e["indexDate"].replace("Z", "+00:00")),
                sum=e["consumptionValue"],
            )
            for e in valid
        ]
        await async_add_external_statistics(self.hass, meta, stats)
