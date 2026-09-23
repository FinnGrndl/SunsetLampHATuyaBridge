"""Optimistic light entity for the one-way Tuya Beacon protocol."""

from __future__ import annotations

from typing import Any, ClassVar

from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
    ATTR_RGB_COLOR,
    ColorMode,
    LightEntity,
)
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import TuyaBeaconConfigEntry
from .const import DOMAIN


async def async_setup_entry(
    _hass: Any,
    entry: TuyaBeaconConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    async_add_entities([TuyaBeaconLight(entry)])


class TuyaBeaconLight(CoordinatorEntity, LightEntity):
    """A light whose state is explicitly marked as assumed."""

    _attr_has_entity_name = True
    _attr_name = None
    _attr_assumed_state = True
    _attr_supported_color_modes: ClassVar[set[ColorMode]] = {ColorMode.RGB}
    _attr_color_mode = ColorMode.RGB

    def __init__(self, entry: TuyaBeaconConfigEntry) -> None:
        super().__init__(entry.runtime_data.coordinator)
        self._entry = entry
        mac = str(self.coordinator.data.get("target_mac", entry.unique_id or "sunset_lamp"))
        self._attr_unique_id = mac.replace(":", "").lower()
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, self._attr_unique_id)},
            name=entry.title,
            manufacturer="Tuya",
            model="P2 Beacon Light",
        )

    @property
    def available(self) -> bool:
        return super().available and bool(self.coordinator.data.get("ready"))

    @property
    def is_on(self) -> bool:
        return bool(self.coordinator.data.get("light", {}).get("on"))

    @property
    def brightness(self) -> int | None:
        return self.coordinator.data.get("light", {}).get("brightness")

    @property
    def rgb_color(self) -> tuple[int, int, int] | None:
        value = self.coordinator.data.get("light", {}).get("rgb_color")
        return tuple(value) if isinstance(value, list) and len(value) == 3 else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        data = self.coordinator.data
        return {
            "assumed_state_reason": "Tuya Beacon control is primarily one-way",
            "protocol_confirmed": data.get("protocol_confirmed", False),
            "confirmation_sources": data.get("confirmation_sources", []),
            "command_counter": data.get("command_counter"),
            "last_beacon_seen": data.get("last_seen"),
        }

    async def async_turn_on(self, **kwargs: Any) -> None:
        payload: dict[str, Any] = {"state": "on"}
        if ATTR_BRIGHTNESS in kwargs:
            payload["brightness"] = kwargs[ATTR_BRIGHTNESS]
        if ATTR_RGB_COLOR in kwargs:
            payload["rgb_color"] = list(kwargs[ATTR_RGB_COLOR])
        result = await self._entry.runtime_data.api.command(payload)
        self._apply_command_result(result)

    async def async_turn_off(self, **_kwargs: Any) -> None:
        result = await self._entry.runtime_data.api.command({"state": "off"})
        self._apply_command_result(result)

    def _apply_command_result(self, result: dict[str, Any]) -> None:
        """Publish the bridge's optimistic result without another HTTP round trip."""
        data = dict(self.coordinator.data)
        data["light"] = result["light"]
        sequences = result.get("sequences")
        if isinstance(sequences, list) and sequences:
            data["command_counter"] = sequences[-1]
        self.coordinator.async_set_updated_data(data)
