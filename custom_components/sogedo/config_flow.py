"""Config flow for the Sogedo water integration.

Uses the interactive Azure AD B2C authorization-code flow with PKCE. Since
device-code and ROPC are disabled by Sogedo, the user logs in via the browser
and pastes the `code` from the redirect URL back into Home Assistant.
"""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv

from .const import (
    CONF_REFRESH_TOKEN,
    CONF_SUBSCRIPTION_ID,
    CONF_SUBSCRIPTION_NAME,
    DOMAIN,
)
from .sogedo_api import (
    SogedoAuthError,
    SogedoClient,
    build_authorize_url,
    exchange_code,
    generate_pkce,
)

_LOGGER = logging.getLogger(__name__)

AUTHORIZE_STEP = "authorize"
TOKEN_STEP = "token"
SUBSCRIPTION_STEP = "subscription"


async def validate_and_build_client(
    hass: HomeAssistant, code: str, code_verifier: str
) -> tuple[SogedoClient, str]:
    """Exchange the code and return (client, refresh_token)."""
    tokens = await hass.async_add_executor_job(exchange_code, code, code_verifier)
    refresh_token = tokens["refresh_token"]
    client = SogedoClient(refresh_token)
    return client, refresh_token


class SogedoConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Sogedo."""

    VERSION = 1

    def __init__(self) -> None:
        self._code_verifier: str | None = None
        self._code_challenge: str | None = None
        self._state: str | None = None
        self._refresh_token: str | None = None
        self._subscriptions: list[dict[str, Any]] = []

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        return await self.async_step_authorize()

    async def async_step_authorize(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show the authorization URL to the user."""
        if user_input is None:
            self._code_verifier, self._code_challenge = generate_pkce()
            self._state = "sogedo-" + self._code_challenge[:8]
            url = build_authorize_url(self._code_challenge, self._state)
            return self.async_show_form(
                step_id=AUTHORIZE_STEP,
                data_schema=vol.Schema({}),
                description_placeholders={"authorize_url": url},
            )
        return await self.async_step_token()

    async def async_step_token(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Exchange the pasted authorization code."""
        errors: dict[str, str] = {}
        if user_input is not None:
            code = user_input["code"]
            try:
                client, self._refresh_token = await validate_and_build_client(
                    self.hass, code, self._code_verifier
                )
                self._subscriptions = await self.hass.async_add_executor_job(
                    client.get_subscriptions
                )
            except SogedoAuthError:
                errors["base"] = "invalid_code"
            except Exception:  # noqa: BLE001
                _LOGGER.exception("Unexpected error during auth")
                errors["base"] = "unknown"

            if not errors:
                if len(self._subscriptions) == 1:
                    return self._create_entry(self._subscriptions[0])
                return await self.async_step_subscription()

        return self.async_show_form(
            step_id=TOKEN_STEP,
            data_schema=vol.Schema({vol.Required("code"): str}),
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
            CONF_REFRESH_TOKEN: self._refresh_token,
            CONF_SUBSCRIPTION_ID: sub["id"],
            CONF_SUBSCRIPTION_NAME: sub["address"],
        }
        title = sub.get("address") or "Sogedo"
        return self.async_create_entry(title=title, data=data)

    async def async_step_reauth(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        return await self.async_step_authorize()
