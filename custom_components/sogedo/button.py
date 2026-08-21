"""Button for the Sogedo water integration."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import SogedoCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: SogedoCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([SogedoBackfillButton(coordinator, entry)])


class SogedoBackfillButton(CoordinatorEntity[SogedoCoordinator], ButtonEntity):
    """Re-run the history backfill (idempotent upsert)."""

    _attr_has_entity_name = True
    _attr_translation_key = "refresh_history"

    def __init__(
        self,
        coordinator: SogedoCoordinator,
        entry: ConfigEntry,
    ) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_refresh_history"

    async def async_press(self) -> None:
        await self.coordinator.async_refresh_history()