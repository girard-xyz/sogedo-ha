"""Config flow tests for the Sogedo integration."""

from homeassistant import config_entries, data_entry_flow


async def test_user_flow_shows_credentials_form(hass):
    result = await hass.config_entries.flow.async_init(
        "sogedo", context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is data_entry_flow.FlowResultType.FORM
    assert result["step_id"] == "credentials"
    assert result["errors"] == {}
