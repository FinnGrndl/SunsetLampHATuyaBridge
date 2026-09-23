"""Tuya Beacon integration."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import BridgeAPIError, TuyaBeaconAPI
from .const import CONF_API_TOKEN, CONF_BASE_URL, PLATFORMS

_LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class RuntimeData:
    api: TuyaBeaconAPI
    coordinator: DataUpdateCoordinator[dict[str, Any]]


TuyaBeaconConfigEntry = ConfigEntry[RuntimeData]


async def async_setup_entry(hass: HomeAssistant, entry: TuyaBeaconConfigEntry) -> bool:
    api = TuyaBeaconAPI(
        async_get_clientsession(hass),
        entry.data[CONF_BASE_URL],
        entry.data[CONF_API_TOKEN],
    )

    async def _update() -> dict[str, Any]:
        try:
            return await api.status()
        except BridgeAPIError as err:
            raise UpdateFailed(f"Tuya Beacon bridge unavailable: {err}") from err

    coordinator = DataUpdateCoordinator(
        hass,
        _LOGGER,
        name="Tuya Beacon bridge",
        update_method=_update,
        update_interval=timedelta(seconds=5),
    )
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = RuntimeData(api, coordinator)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: TuyaBeaconConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
