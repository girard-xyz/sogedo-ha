"""Config flow for the Sogedo water integration.

Signs in to Sogedo with the account email/password. The credentials are kept in
the config entry so the client can sign in again when its refresh token lapses.
"""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.core import HomeAssistant
from homeassistant.helpers.selector import TextSelector, TextSelectorType
from homeassistant.helpers.storage import Store

from .const import (
    CONF_EMAIL,
    CONF_PASSWORD,
    CONF_REFRESH_TOKEN,
    CONF_SUBSCRIPTION_ID,
    CONF_SUBSCRIPTION_NAME,
    DOMAIN,
    STORAGE_VERSION,
)
from .sogedo_api import SogedoAuthError, SogedoClient, login

_LOGGER = logging.getLogger(__name__)

CREDENTIALS_STEP = "credentials"
SUBSCRIPTION_STEP = "subscription"


def _credentials_schema() -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(CONF_EMAIL): str,
            vol.Required(CONF_PASSWORD): TextSelector(
                {"type": TextSelectorType.PASSWORD}
            ),
        }
    )


async def validate_credentials(
    hass: HomeAssistant, email: str, password: str
) -> tuple[SogedoClient, str]:
    """Sign in and return (client, refresh_token)."""
    tokens = await hass.async_add_executor_job(login, email, password)
    refresh_token = tokens["refresh_token"]
    return SogedoClient(email, password, refresh_token), refresh_token


class SogedoConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Sogedo."""

    VERSION = 1

    def __init__(self) -> None:
        self._email: str = ""
        self._password: str = ""
        self._refresh_token: str | None = None
        self._subscriptions: list[dict[str, Any]] = []

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        return await self.async_step_credentials(user_input)

    async def async_step_credentials(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Collect the Sogedo email and password."""
        errors: dict[str, str] = {}
        if user_input is not None:
            email = user_input[CONF_EMAIL].strip()
            password = user_input[CONF_PASSWORD]
            try:
                client, self._refresh_token = await validate_credentials(
                    self.hass, email, password
                )
                self._subscriptions = await self.hass.async_add_executor_job(
                    client.get_subscriptions
                )
            except SogedoAuthError:
                errors["base"] = "invalid_auth"
            except Exception:  # noqa: BLE001
                _LOGGER.exception("Unexpected error during auth")
                errors["base"] = "unknown"

            if not errors:
                self._email = email
                self._password = password
                if self.source == config_entries.SOURCE_REAUTH:
                    return await self._update_existing_entry()
                if len(self._subscriptions) == 1:
                    return self._create_entry(self._subscriptions[0])
                return await self.async_step_subscription()

        return self.async_show_form(
            step_id=CREDENTIALS_STEP,
            data_schema=_credentials_schema(),
            errors=errors,
        )

    async def async_step_subscription(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Let the user pick a subscription when multiple exist."""
        if user_input is not None:
            sub = next(
                (s for s in self._subscriptions if s["id"] == user_input["subscription"]),
                self._subscriptions[0],
            )
            return self._create_entry(sub)

        options = {
            s["id"]: f"{s['address']} ({s['contractNumber']})"
            for s in self._subscriptions
        }
        return self.async_show_form(
            step_id=SUBSCRIPTION_STEP,
            data_schema=vol.Schema({vol.Required("subscription"): vol.In(options)}),
        )

    def _create_entry(self, sub: dict[str, Any]) -> ConfigFlowResult:
        data = {
            CONF_EMAIL: self._email,
            CONF_PASSWORD: self._password,
            CONF_REFRESH_TOKEN: self._refresh_token,
            CONF_SUBSCRIPTION_ID: sub["id"],
            CONF_SUBSCRIPTION_NAME: sub["address"],
        }
        title = sub.get("address") or "Sogedo"
        return self.async_create_entry(title=title, data=data)

    async def _update_existing_entry(self) -> ConfigFlowResult:
        """Update the existing entry with fresh credentials (entities preserved)."""
        entry = self._get_reauth_entry()
        data = dict(entry.data)
        data[CONF_EMAIL] = self._email
        data[CONF_PASSWORD] = self._password
        data[CONF_REFRESH_TOKEN] = self._refresh_token
        # Keep the local token store in sync so a stale stored token can't
        # override the freshly obtained one on the following setup.
        try:
            store = Store(self.hass, STORAGE_VERSION, f"{DOMAIN}.{entry.entry_id}")
            await store.async_save({"refresh_token": self._refresh_token})
        except Exception:  # noqa: BLE001
            _LOGGER.debug("Could not persist the reauth token", exc_info=True)
        return self.async_update_reload_and_abort(entry, data=data)

    async def async_step_reauth(
        self, entry_data: dict[str, Any]
    ) -> ConfigFlowResult:
        # HA passes the entry data here; show the credentials form instead.
        return await self.async_step_credentials()
