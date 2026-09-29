"""State, diagnostics, and guarded P2 Beacon command orchestration."""

from __future__ import annotations

import colorsys
import hashlib
import json
import logging
import os
import threading
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .mgmt import LegacyAdvertiser
from .protocol import (
    PROTOCOL_NAME,
    P2Frame,
    build_p2_frame,
    decode_datapoints,
    derive_beacon_key,
    dp_colour,
    dp_on_off,
    expected_on_air_advertisement,
    parse_local_key,
    parse_node_id,
    parse_p2_frame,
)

_LOGGER = logging.getLogger(__name__)


class BridgeError(RuntimeError):
    """Base bridge error."""


class NotReadyError(BridgeError):
    """Control was requested before the safety gates passed."""


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _packet_option(options: dict[str, Any], name: str) -> bytes | None:
    raw = options.get(name)
    if raw is None or not str(raw).strip():
        return None
    value = str(raw).replace(" ", "")
    try:
        packet = bytes.fromhex(value)
    except ValueError as err:
        raise ValueError(f"{name} must be hexadecimal") from err
    if len(packet) != 26:
        raise ValueError(f"{name} must contain one 26-byte P2 frame")
    return packet


@dataclass(frozen=True, slots=True)
class BridgeConfig:
    target_mac: str
    local_key: bytes
    beacon_key: bytes | None
    api_token: str
    target_node_id: int | None
    source_id: int
    controller_index: int
    scan_enabled: bool
    advertising_instance: int
    advertising_interval_ms: int
    tx_power_dbm: int
    force_legacy_advertising: bool
    transmit_seconds: float
    control_enabled: bool
    listen_host: str
    listen_port: int
    state_path: Path
    provisioning_path: Path
    confirmation_source: str | None = None

    @classmethod
    def from_options(cls, options: dict[str, Any], data_dir: Path = Path("/data")) -> BridgeConfig:
        local_key = parse_local_key(str(options.get("local_key", "")))
        token = str(options.get("api_token", ""))
        if len(token) < 24:
            raise ValueError("api_token must contain at least 24 characters")
        mac = str(options.get("target_mac", "")).upper().replace("-", ":")
        parts = mac.split(":")
        if len(parts) != 6 or any(
            len(part) != 2 or any(char not in "0123456789ABCDEF" for char in part)
            for part in parts
        ):
            raise ValueError("target_mac must be a six-byte Bluetooth address")

        off_packet = _packet_option(options, "key_derivation_off_packet")
        on_packet = _packet_option(options, "key_derivation_on_packet")
        if (off_packet is None) != (on_packet is None):
            raise ValueError("provide both key-derivation packets or leave both empty")

        beacon_key: bytes | None = None
        target_node_id: int | None = None
        confirmation_source: str | None = None
        if off_packet is not None and on_packet is not None:
            off_key = derive_beacon_key(off_packet, local_key, dp_on_off(False))
            on_key = derive_beacon_key(on_packet, local_key, dp_on_off(True))
            if off_key != on_key:
                raise ValueError("known OFF/ON captures derive different beacon keys")

            target_node_id = int.from_bytes(off_packet[3:5], "big")
            if int.from_bytes(on_packet[3:5], "big") != target_node_id:
                raise ValueError("known OFF/ON captures have different destinations")
            configured_target = str(options.get("target_node_id", "")).strip()
            if configured_target and parse_node_id(configured_target) != target_node_id:
                raise ValueError("key-derivation packet destination does not match target_node_id")
            # Decrypting both independent captures is the protocol
            # confirmation gate. No key or decrypted bytes are logged.
            if parse_p2_frame(off_packet, encryption_key=local_key, beacon_key=off_key) is None:
                raise ValueError("OFF capture could not be decrypted")
            if parse_p2_frame(on_packet, encryption_key=local_key, beacon_key=off_key) is None:
                raise ValueError("ON capture could not be decrypted")
            beacon_key = off_key
            confirmation_source = "configured_off_on_captures"

        return cls(
            target_mac=mac,
            local_key=local_key,
            beacon_key=beacon_key,
            api_token=token,
            target_node_id=target_node_id,
            source_id=parse_node_id(str(options.get("source_id", "7FFE")), "source ID"),
            controller_index=int(options.get("controller_index", 0)),
            scan_enabled=bool(options.get("scan_enabled", True)),
            advertising_instance=int(options.get("advertising_instance", 12)),
            advertising_interval_ms=int(options.get("advertising_interval_ms", 100)),
            tx_power_dbm=int(options.get("tx_power_dbm", 7)),
            force_legacy_advertising=bool(options.get("force_legacy_advertising", False)),
            transmit_seconds=float(options.get("transmit_seconds", 0.35)),
            control_enabled=bool(options.get("control_enabled", False)),
            listen_host=str(options.get("listen_host", "127.0.0.1")),
            listen_port=int(options.get("listen_port", 8099)),
            state_path=data_dir / "state.json",
            provisioning_path=data_dir / "provisioning.json",
            confirmation_source=confirmation_source,
        )


class TuyaBeaconBridge:
    """Thread-safe, optimistic bridge for the one-way P2 control channel."""

    def __init__(self, config: BridgeConfig) -> None:
        self.config = config
        self.advertiser = LegacyAdvertiser(
            config.controller_index,
            config.advertising_instance,
            config.transmit_seconds,
            config.advertising_interval_ms,
            config.tx_power_dbm,
            config.force_legacy_advertising,
        )
        self._lock = threading.RLock()
        self._command_lock = threading.Lock()
        self._last_seen: str | None = None
        self._last_error: str | None = None
        self._beacon_key = config.beacon_key
        self._target_node_id = config.target_node_id
        self._confirmation_source = config.confirmation_source
        self._provisioning_candidates: dict[tuple[bytes, int], set[bool]] = {}
        self._provisioning_observed: set[bool] = set()
        if self._beacon_key is None:
            self._load_provisioning()
        self._state = self._load_state()

    def _local_key_fingerprint(self) -> str:
        return hashlib.sha256(self.config.local_key).hexdigest()

    def _load_provisioning(self) -> None:
        try:
            data = json.loads(self.config.provisioning_path.read_text(encoding="utf-8"))
            if data.get("local_key_fingerprint") != self._local_key_fingerprint():
                _LOGGER.info("Ignoring provisioning saved for a different local key")
                return
            key = bytes.fromhex(str(data["beacon_key"]))
            target = parse_node_id(str(data["target_node_id"]))
            if len(key) != 16:
                raise ValueError("stored beacon key has the wrong length")
        except FileNotFoundError:
            return
        except (KeyError, OSError, TypeError, ValueError, json.JSONDecodeError) as err:
            _LOGGER.warning("Ignoring invalid persisted provisioning: %s", err)
            return
        self._beacon_key = key
        self._target_node_id = target
        self._confirmation_source = "automatic_off_on_training"

    def _save_provisioning_locked(self) -> None:
        self.config.provisioning_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.config.provisioning_path.with_suffix(".tmp")
        data = {
            "version": 1,
            "local_key_fingerprint": self._local_key_fingerprint(),
            "beacon_key": self._beacon_key.hex() if self._beacon_key else "",
            "target_node_id": f"{self._target_node_id:04X}",
        }
        temporary.write_text(json.dumps(data, separators=(",", ":")), encoding="utf-8")
        os.chmod(temporary, 0o600)
        temporary.replace(self.config.provisioning_path)

    def _load_state(self) -> dict[str, Any]:
        state: dict[str, Any] = {
            "sequence": -1,
            "light": {
                "on": False,
                "rgb_color": [255, 128, 64],
                "brightness": 255,
            },
        }
        try:
            loaded = json.loads(self.config.state_path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                state.update(loaded)
        except FileNotFoundError:
            pass
        except (OSError, json.JSONDecodeError) as err:
            _LOGGER.warning("Ignoring invalid persisted state: %s", err)
        sequence = state.get("sequence")
        # State created by the discarded three-byte protocol implementation
        # must not leak into this independent two-byte source sequence.
        if not isinstance(sequence, int) or not -1 <= sequence <= 0xFFFF:
            state["sequence"] = -1
        return state

    def _save_state_locked(self) -> None:
        self.config.state_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.config.state_path.with_suffix(".tmp")
        temporary.write_text(json.dumps(self._state, separators=(",", ":")), encoding="utf-8")
        os.chmod(temporary, 0o600)
        temporary.replace(self.config.state_path)

    def on_packet(self, packet: bytes, address: str) -> None:
        """Provision from or decrypt one raw P2 advertisement."""
        with self._lock:
            beacon_key = self._beacon_key
            target_node_id = self._target_node_id
        if beacon_key is None or target_node_id is None:
            self._consider_provisioning_packet(packet)
            with self._lock:
                beacon_key = self._beacon_key
                target_node_id = self._target_node_id
            if beacon_key is None or target_node_id is None:
                return

        if int.from_bytes(packet[1:3], "big") == target_node_id:
            encryption_key = beacon_key
        elif int.from_bytes(packet[3:5], "big") == target_node_id:
            encryption_key = self.config.local_key
        else:
            return
        frame = parse_p2_frame(
            packet,
            encryption_key=encryption_key,
            beacon_key=beacon_key,
        )
        if frame is not None:
            self.on_frame(frame, address)

    def _consider_provisioning_packet(self, packet: bytes) -> None:
        if len(packet) != 26 or packet[0] != 0x0B or packet[7] != 0x05:
            return
        target_node_id = int.from_bytes(packet[3:5], "big")
        for state in (False, True):
            try:
                beacon_key = derive_beacon_key(packet, self.config.local_key, dp_on_off(state))
            except ValueError:
                continue
            identity = (beacon_key, target_node_id)
            with self._lock:
                observed = self._provisioning_candidates.setdefault(identity, set())
                first_observation = state not in observed
                observed.add(state)
                self._provisioning_observed.add(state)
                if first_observation:
                    _LOGGER.info(
                        "Provisioning observed authenticated %s command; now send %s in Smart Life",
                        "ON" if state else "OFF",
                        "OFF" if state else "ON",
                    )
                if observed != {False, True}:
                    return
                self._beacon_key = beacon_key
                self._target_node_id = target_node_id
                self._confirmation_source = "automatic_off_on_training"
                self._save_provisioning_locked()
            _LOGGER.info(
                "Provisioning complete for target node 0x%04X; no key material was logged",
                target_node_id,
            )
            return

    def on_frame(self, frame: P2Frame, address: str) -> None:
        """Update assumed state from a decrypted phone or lamp frame."""
        with self._lock:
            self._last_seen = _now()
            if frame.destination_id != self._target_node_id or frame.subcommand != 0x05:
                return
            datapoints = decode_datapoints(frame.payload)
            light = dict(self._state["light"])
            if 1 in datapoints and datapoints[1][0] == 1 and datapoints[1][1]:
                light["on"] = bool(datapoints[1][1][0])
            if 11 in datapoints and datapoints[11][0] == 0 and len(datapoints[11][1]) == 4:
                raw = datapoints[11][1]
                hue = min(360, int.from_bytes(raw[:2], "big")) / 360
                saturation = min(100, raw[2]) / 100
                value = min(100, raw[3]) / 100
                red, green, blue = colorsys.hsv_to_rgb(hue, saturation, value)
                light["rgb_color"] = [round(red * 255), round(green * 255), round(blue * 255)]
                light["brightness"] = max(1, round(value * 255))
                light["on"] = True
            self._state["light"] = light
            self._save_state_locked()
            _LOGGER.info(
                "Accepted decrypted P2 state update from %s (source=0x%04x, sequence=%d)",
                address,
                frame.source_id,
                frame.sequence,
            )

    def status(self) -> dict[str, Any]:
        """Return diagnostics without keys, plaintext, ciphertext, or samples."""
        with self._lock:
            confirmed = self._beacon_key is not None and self._target_node_id is not None
            return {
                "ok": True,
                "protocol": PROTOCOL_NAME,
                "target_mac": self.config.target_mac,
                "protocol_confirmed": confirmed,
                "confirmation_sources": [self._confirmation_source]
                if self._confirmation_source
                else [],
                "last_seen": self._last_seen,
                "command_counter": self._state["sequence"],
                "control_enabled": self.config.control_enabled,
                "ready": self.config.control_enabled and confirmed,
                "assumed_state": True,
                "last_error": self._last_error,
                "adapter": {
                    "index": self.config.controller_index,
                    "reserved_advertising_instance": self.config.advertising_instance,
                    "advertising_interval_ms": self.config.advertising_interval_ms,
                    "tx_power_dbm": self.config.tx_power_dbm,
                    "force_legacy_advertising": self.config.force_legacy_advertising,
                },
                "source_id": f"{self.config.source_id:04X}",
                "target_node_id": f"{self._target_node_id:04X}"
                if self._target_node_id is not None
                else None,
                "provisioning": {
                    "required": not confirmed,
                    "observed_commands": [
                        "on" if state else "off" for state in sorted(self._provisioning_observed)
                    ],
                },
                "light": dict(self._state["light"]),
            }

    def capabilities(self) -> dict[str, Any]:
        features = self.advertiser.capabilities()
        return {
            "supported_flags": features.supported_flags,
            "max_advertising_length": features.max_advertising_length,
            "max_scan_response_length": features.max_scan_response_length,
            "max_instances": features.max_instances,
            "active_instances": list(features.active_instances),
        }

    def _ensure_ready(self) -> None:
        if not self.config.control_enabled:
            raise NotReadyError("control is disabled in the app configuration")
        if self._beacon_key is None or self._target_node_id is None:
            raise NotReadyError("provisioning is incomplete; send OFF and ON in Smart Life")

    def _emit_datapoint(self, payload: bytes) -> int:
        beacon_key = self._beacon_key
        target_node_id = self._target_node_id
        if beacon_key is None or target_node_id is None:
            raise NotReadyError("provisioning is incomplete")
        with self._lock:
            sequence = (int(self._state["sequence"]) + 1) & 0xFFFF
            # Persist before transmission. Burning a sequence after an I/O
            # error is safe; reusing an accepted sequence is not.
            self._state["sequence"] = sequence
            self._save_state_locked()
        packet = build_p2_frame(
            source_id=self.config.source_id,
            destination_id=target_node_id,
            sequence=sequence,
            payload=payload,
            local_key=self.config.local_key,
            beacon_key=beacon_key,
        )
        try:
            self.advertiser.emit(expected_on_air_advertisement(packet))
        except Exception as err:
            with self._lock:
                self._last_error = str(err)
            raise
        with self._lock:
            self._last_error = None
        return sequence

    def command(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Apply one Home Assistant light command."""
        with self._command_lock:
            self._ensure_ready()
            desired = str(payload.get("state", "on")).lower()
            if desired not in ("on", "off"):
                raise ValueError("state must be 'on' or 'off'")
            sequences: list[int] = []
            if desired == "off":
                sequences.append(self._emit_datapoint(dp_on_off(False)))
                with self._lock:
                    self._state["light"]["on"] = False
                    self._save_state_locked()
                    light = dict(self._state["light"])
                return {"ok": True, "assumed_state": True, "sequences": sequences, "light": light}

            with self._lock:
                current_light = dict(self._state["light"])
            has_colour_change = "rgb_color" in payload or "brightness" in payload
            rgb = payload.get("rgb_color", current_light["rgb_color"])
            if not isinstance(rgb, (list, tuple)) or len(rgb) != 3:
                raise ValueError("rgb_color must contain exactly three values")
            rgb_values = [max(0, min(255, int(component))) for component in rgb]
            brightness = max(1, min(255, int(payload.get("brightness", current_light["brightness"]))))
            datapoints = dp_on_off(True)
            if has_colour_change:
                red, green, blue = (component / 255 for component in rgb_values)
                hue_fraction, saturation_fraction, _ = colorsys.rgb_to_hsv(red, green, blue)
                hue = min(360, round(hue_fraction * 360))
                saturation = max(0, min(100, round(saturation_fraction * 100)))
                value = max(1, min(100, round(brightness * 100 / 255)))
                # P2 accepts multiple compact datapoints in its 16-byte
                # plaintext. Sending power and colour together avoids a full
                # second advertising window and prevents an intermediate
                # flash in the previous colour.
                datapoints += dp_colour(hue, saturation, value)
            sequences.append(self._emit_datapoint(datapoints))

            with self._lock:
                self._state["light"] = {
                    "on": True,
                    "rgb_color": rgb_values,
                    "brightness": brightness,
                }
                self._save_state_locked()
                light = dict(self._state["light"])
            return {"ok": True, "assumed_state": True, "sequences": sequences, "light": light}
