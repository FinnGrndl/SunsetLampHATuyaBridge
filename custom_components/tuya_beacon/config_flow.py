"""Config flow for Tuya Beacon."""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_NAME
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import TextSelector, TextSelectorConfig, TextSelectorType

from .api import BridgeAPIError, TuyaBeaconAPI
from .const import CONF_API_TOKEN, CONF_BASE_URL, DEFAULT_BASE_URL, DOMAIN


class TuyaBeaconConfigFlow(ConfigFlow, domain=DOMAIN):
    """Configure the local bridge."""

    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            api = TuyaBeaconAPI(
                async_get_clientsession(self.hass),
                user_input[CONF_BASE_URL],
                user_input[CONF_API_TOKEN],
            )
            try:
                status = await api.status()
            except BridgeAPIError:
                errors["base"] = "cannot_connect"
            else:
                unique = str(status.get("target_mac", "sunset_lamp")).replace(":", "").lower()
                await self.async_set_unique_id(unique)
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=user_input[CONF_NAME],
                    data=user_input,
                )

        schema = vol.Schema(
            {
                vol.Required(CONF_NAME, default="Tuya Beacon Light"): str,
                vol.Required(CONF_BASE_URL, default=DEFAULT_BASE_URL): str,
                vol.Required(CONF_API_TOKEN): TextSelector(
                    TextSelectorConfig(type=TextSelectorType.PASSWORD)
                ),
            }
        )
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)
