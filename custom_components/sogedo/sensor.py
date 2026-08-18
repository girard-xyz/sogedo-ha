"""Sensors for the Sogedo water integration."""

from __future__ import annotations

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfVolume
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import SogedoCoordinator

DESCRIPTIONS = [
    SensorEntityDescription(
        key="daily_consumption",
        name="Daily consumption",
        native_unit_of_measurement=UnitOfVolume.CUBIC_METERS,
        device_class=SensorDeviceClass.WATER,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SensorEntityDescription(
        key="cumulative",
        name="Cumulative consumption",
        native_unit_of_measurement=UnitOfVolume.CUBIC_METERS,
        device_class=SensorDeviceClass.WATER,
        state_class=SensorStateClass.TOTAL_INCREASING,
    ),
]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: SogedoCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        SogedoSensor(coordinator, entry, description)
        for description in DESCRIPTIONS
    )


class SogedoSensor(CoordinatorEntity[SogedoCoordinator], SensorEntity):
    """A Sogedo water sensor."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: SogedoCoordinator,
        entry: ConfigEntry,
        description: SensorEntityDescription,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{entry.entry_id}_{description.key}"
        self._attr_translation_key = description.key

    @property
    def native_value(self) -> float | None:
        return self.coordinator.data.get(self.entity_description.key)

    @property
    def available(self) -> bool:
        return (
            super().available
            and self.coordinator.data is not None
            and self.coordinator.data.get("available")
        )
