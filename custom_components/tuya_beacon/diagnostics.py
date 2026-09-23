"""Diagnostics for Tuya Beacon."""

from __future__ import annotations

from typing import Any

from homeassistant.core import HomeAssistant

from . import TuyaBeaconConfigEntry
from .const import CONF_API_TOKEN


async def async_get_config_entry_diagnostics(
    _hass: HomeAssistant, entry: TuyaBeaconConfigEntry
) -> dict[str, Any]:
    config = dict(entry.data)
    config[CONF_API_TOKEN] = "**REDACTED**"
    bridge = dict(entry.runtime_data.coordinator.data)
    if "target_mac" in bridge:
        bridge["target_mac"] = "**REDACTED**"
    return {"config": config, "bridge": bridge}
