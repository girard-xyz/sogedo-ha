"""Coordinator for polling Sogedo consumption data."""

from __future__ import annotations

import logging
from datetime import timedelta

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import SCAN_INTERVAL_SECONDS, UPDATE_DATE_OFFSET
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
        except Exception as err:
            raise UpdateFailed(f"Sogedo update failed: {err}") from err

        # Most recent day with a real reading is the target (J-1).
        latest = select_latest(entries)

        return {
            "daily_consumption": latest["consumptionValue"] if latest else None,
            "cumulative": latest["indexValue"] if latest else None,
            "index_date": latest["indexDate"] if latest else None,
            "available": bool(latest and latest.get("isIndexValueAvailable")),
        }
