"""The Sogedo water integration."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from .const import (
    CONF_REFRESH_TOKEN,
    CONF_SUBSCRIPTION_ID,
    DOMAIN,
    PLATFORMS,
    STORAGE_VERSION,
)
from .coordinator import SogedoCoordinator
from .sogedo_api import SogedoClient


def token_store(hass: HomeAssistant, entry: ConfigEntry) -> Store:
    """Return the local store holding the rotating refresh token."""
    return Store(hass, STORAGE_VERSION, f"{DOMAIN}.{entry.entry_id}")


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    # Prefer the latest rotated refresh token so restarts never force a re-auth
    # (Sogedo's refresh token only lives ~24h but is renewed on every poll).
    store = token_store(hass, entry)
    stored = await store.async_load()
    refresh_token = (stored or {}).get("refresh_token") or entry.data[
        CONF_REFRESH_TOKEN
    ]

    client = SogedoClient(refresh_token)

    async def _persist_token(token: str) -> None:
        await store.async_save({"refresh_token": token})

    coordinator = SogedoCoordinator(
        hass,
        client,
        entry.data[CONF_SUBSCRIPTION_ID],
        entry,
        persist_token=_persist_token,
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