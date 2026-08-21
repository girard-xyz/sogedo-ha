"""The Sogedo water integration."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import CONF_REFRESH_TOKEN, CONF_SUBSCRIPTION_ID, DOMAIN, PLATFORMS
from .coordinator import SogedoCoordinator
from .sogedo_api import SogedoClient


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    client = SogedoClient(entry.data[CONF_REFRESH_TOKEN])
    coordinator = SogedoCoordinator(
        hass, client, entry.data[CONF_SUBSCRIPTION_ID], entry
    )
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator

    # If auth is already expired, this raises ConfigEntryAuthFailed, which HA
    # turns into an automatic reauth prompt (no need to delete the entry).
    await coordinator.async_config_entry_first_refresh()

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)
    return unload_ok
