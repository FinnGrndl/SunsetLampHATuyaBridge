"""Minimal Linux Bluetooth Management API transport.

Only Read Advertising Features, Add Advertising, and Remove Advertising are
implemented.  No adapter-wide settings are changed.
"""

from __future__ import annotations

import logging
import math
import socket
import struct
import threading
import time
from dataclasses import dataclass
from typing import Self

MGMT_INDEX_NONE = 0xFFFF
HCI_CHANNEL_CONTROL = getattr(socket, "HCI_CHANNEL_CONTROL", 3)

MGMT_EV_CMD_COMPLETE = 0x0001
MGMT_EV_CMD_STATUS = 0x0002
MGMT_OP_READ_ADV_FEATURES = 0x003D
MGMT_OP_ADD_ADVERTISING = 0x003E
MGMT_OP_REMOVE_ADVERTISING = 0x003F
MGMT_OP_ADD_EXT_ADV_PARAMS = 0x0054
MGMT_OP_ADD_EXT_ADV_DATA = 0x0055

MGMT_ADV_FLAG_CONNECTABLE = 1 << 0
MGMT_ADV_PARAM_TIMEOUT = 1 << 13
MGMT_ADV_PARAM_INTERVAL = 1 << 14
MGMT_ADV_PARAM_TX_POWER = 1 << 15

_LOGGER = logging.getLogger(__name__)

_STATUS_NAMES = {
    0x00: "success",
    0x01: "unknown command",
    0x02: "not connected",
    0x03: "failed",
    0x04: "connect failed",
    0x05: "authentication failed",
    0x06: "not paired",
    0x07: "no resources",
    0x08: "timeout",
    0x09: "already connected",
    0x0A: "busy",
    0x0B: "rejected",
    0x0C: "not supported",
    0x0D: "invalid parameters",
    0x0E: "disconnected",
    0x0F: "not powered",
    0x10: "cancelled",
    0x11: "invalid index",
    0x12: "rfkill",
    0x13: "already paired",
    0x14: "permission denied",
}


class MgmtError(RuntimeError):
    """A Bluetooth Management API operation failed."""

    def __init__(self, message: str, *, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


@dataclass(frozen=True, slots=True)
class AdvertisingFeatures:
    supported_flags: int
    max_advertising_length: int
    max_scan_response_length: int
    max_instances: int
    active_instances: tuple[int, ...]


class ManagementSocket:
    """Synchronous command client for the kernel Bluetooth control channel."""

    def __init__(self, controller_index: int, timeout: float = 5.0) -> None:
        if not 0 <= controller_index <= 0xFFFE:
            raise ValueError("controller index must be between 0 and 65534")
        self.controller_index = controller_index
        self.timeout = timeout
        self._socket: socket.socket | None = None

    def __enter__(self) -> Self:
        try:
            protocol = socket.BTPROTO_HCI
            family = socket.AF_BLUETOOTH
        except AttributeError as err:
            raise MgmtError("Python was built without Linux Bluetooth socket support") from err
        sock = socket.socket(
            family,
            socket.SOCK_RAW | getattr(socket, "SOCK_CLOEXEC", 0),
            protocol,
        )
        sock.settimeout(self.timeout)
        # The management control channel is global; commands themselves carry
        # the target controller index.
        sock.bind((MGMT_INDEX_NONE, HCI_CHANNEL_CONTROL))
        self._socket = sock
        return self

    def __exit__(self, *_args: object) -> None:
        if self._socket is not None:
            self._socket.close()
            self._socket = None

    def command(self, opcode: int, parameters: bytes = b"") -> bytes:
        """Send one command and return its Command Complete payload."""
        if self._socket is None:
            raise RuntimeError("management socket is not open")
        packet = struct.pack("<HHH", opcode, self.controller_index, len(parameters)) + parameters
        self._socket.sendall(packet)
        deadline = time.monotonic() + self.timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise MgmtError(f"management opcode 0x{opcode:04x} timed out")
            self._socket.settimeout(remaining)
            event = self._socket.recv(4096)
            if len(event) < 6:
                continue
            event_code, index, length = struct.unpack_from("<HHH", event)
            payload = event[6 : 6 + length]
            if index != self.controller_index or len(payload) < 3:
                continue
            if event_code not in (MGMT_EV_CMD_COMPLETE, MGMT_EV_CMD_STATUS):
                continue
            response_opcode = struct.unpack_from("<H", payload)[0]
            if response_opcode != opcode:
                continue
            status = payload[2]
            if status:
                name = _STATUS_NAMES.get(status, "unknown status")
                raise MgmtError(
                    f"management opcode 0x{opcode:04x} failed: {name} (0x{status:02x})",
                    status=status,
                )
            if event_code == MGMT_EV_CMD_STATUS:
                return b""
            return payload[3:]

    def read_advertising_features(self) -> AdvertisingFeatures:
        data = self.command(MGMT_OP_READ_ADV_FEATURES)
        if len(data) < 8:
            raise MgmtError("short Read Advertising Features response")
        flags, max_adv, max_scan, max_instances, count = struct.unpack_from("<IBBBB", data)
        if len(data) < 8 + count:
            raise MgmtError("truncated active advertising instance list")
        return AdvertisingFeatures(flags, max_adv, max_scan, max_instances, tuple(data[8 : 8 + count]))

    def add_advertisement(
        self,
        *,
        instance: int,
        advertising_data: bytes,
        hold_seconds: float,
        interval_ms: int,
        tx_power_dbm: int,
        force_legacy: bool,
    ) -> int:
        """Add one legacy PDU, preferring explicit advertising intervals."""
        if not 1 <= instance <= 0xFF:
            raise ValueError("advertising instance must be between 1 and 255")
        if not 0 < hold_seconds <= 60:
            raise ValueError("hold_seconds must be between 0 and 60")
        if len(advertising_data) > 0xFF:
            raise ValueError("advertising data is too long")
        if not 20 <= interval_ms <= 10_485:
            raise ValueError("advertising interval must be between 20 and 10485 ms")
        if not -127 <= tx_power_dbm <= 20:
            raise ValueError("advertising TX power must be between -127 and 20 dBm")
        if force_legacy:
            return self._add_legacy_advertisement(
                instance=instance,
                advertising_data=advertising_data,
                hold_seconds=hold_seconds,
            )
        try:
            return self._add_extended_advertisement(
                instance=instance,
                advertising_data=advertising_data,
                hold_seconds=hold_seconds,
                interval_ms=interval_ms,
                tx_power_dbm=tx_power_dbm,
            )
        except MgmtError as err:
            # Parameters may already have reserved the instance when the data
            # command fails. Remove only this instance before retrying.
            try:
                self.remove_advertisement(instance)
            except MgmtError:
                pass
            if err.status not in (0x01, 0x0C, 0x0D):
                raise
            _LOGGER.warning(
                "Explicit advertising interval unsupported; using legacy kernel defaults: %s",
                err,
            )
            return self._add_legacy_advertisement(
                instance=instance,
                advertising_data=advertising_data,
                hold_seconds=hold_seconds,
            )

    def _add_extended_advertisement(
        self,
        *,
        instance: int,
        advertising_data: bytes,
        hold_seconds: float,
        interval_ms: int,
        tx_power_dbm: int,
    ) -> int:
        """Configure a legacy PDU through the interval-aware MGMT commands."""
        timeout = min(0xFFFF, max(2, math.ceil(hold_seconds) + 2))
        interval_slots = round(interval_ms / 0.625)
        flags = (
            MGMT_ADV_FLAG_CONNECTABLE
            | MGMT_ADV_PARAM_TIMEOUT
            | MGMT_ADV_PARAM_INTERVAL
            | MGMT_ADV_PARAM_TX_POWER
        )
        parameters = struct.pack(
            "<BIHHIIb",
            instance,
            flags,
            0,  # duration is irrelevant while this is the sole active instance
            timeout,
            interval_slots,
            interval_slots,
            tx_power_dbm,
        )
        response = self.command(MGMT_OP_ADD_EXT_ADV_PARAMS, parameters)
        if len(response) != 4:
            raise MgmtError("invalid Add Extended Advertising Parameters response")
        added, _tx_power, max_adv_length, _max_scan_length = struct.unpack("<BbBB", response)
        if added != instance:
            raise MgmtError(f"kernel allocated unexpected advertising instance {added}")
        if len(advertising_data) > max_adv_length:
            raise MgmtError("advertising data exceeds the interval-aware adapter limit")
        data = bytes((instance, len(advertising_data), 0)) + advertising_data
        response = self.command(MGMT_OP_ADD_EXT_ADV_DATA, data)
        if response != bytes((instance,)):
            raise MgmtError("invalid Add Extended Advertising Data response")
        return instance

    def _add_legacy_advertisement(
        self,
        *,
        instance: int,
        advertising_data: bytes,
        hold_seconds: float,
    ) -> int:
        """Use the older MGMT command when explicit intervals are unavailable."""
        # Flags AD data is supplied explicitly by the caller.  Using the MGMT
        # DISCOV bit would make the kernel synthesize 0x02 on a dual-mode Intel
        # adapter, while this protocol requires the exact value 0x06.
        flags = MGMT_ADV_FLAG_CONNECTABLE
        # Timeout is a crash-safety net.  Normal cleanup removes the instance
        # immediately after hold_seconds.
        timeout = min(0xFFFF, max(2, math.ceil(hold_seconds) + 2))
        parameters = struct.pack(
            "<BIHHBB",
            instance,
            flags,
            0,  # duration: kernel default; irrelevant with hardware offload
            timeout,
            len(advertising_data),
            0,  # no scan response: name and UUID must both be in ADV_IND
        ) + advertising_data
        response = self.command(MGMT_OP_ADD_ADVERTISING, parameters)
        if len(response) != 1:
            raise MgmtError("invalid Add Advertising response")
        return response[0]

    def remove_advertisement(self, instance: int) -> None:
        """Remove exactly one owned advertising instance."""
        response = self.command(MGMT_OP_REMOVE_ADVERTISING, bytes((instance,)))
        if response and response != bytes((instance,)):
            raise MgmtError("Remove Advertising returned an unexpected instance")


class LegacyAdvertiser:
    """Safely owns one fixed high-numbered advertising instance."""

    def __init__(
        self,
        controller_index: int,
        instance: int,
        hold_seconds: float,
        interval_ms: int,
        tx_power_dbm: int,
        force_legacy: bool,
    ) -> None:
        self.controller_index = controller_index
        self.instance = instance
        self.hold_seconds = hold_seconds
        self.interval_ms = interval_ms
        self.tx_power_dbm = tx_power_dbm
        self.force_legacy = force_legacy
        self._lock = threading.Lock()

    def capabilities(self) -> AdvertisingFeatures:
        with ManagementSocket(self.controller_index) as manager:
            return manager.read_advertising_features()

    def emit(self, advertising_data: bytes) -> None:
        """Emit and remove one advertisement without touching global state."""
        with self._lock, ManagementSocket(self.controller_index) as manager:
            features = manager.read_advertising_features()
            if self.instance > features.max_instances:
                raise MgmtError(
                    f"configured instance {self.instance} exceeds adapter maximum "
                    f"{features.max_instances}"
                )
            if self.instance in features.active_instances:
                raise MgmtError(
                    f"advertising instance {self.instance} is already active; refusing to overwrite it"
                )
            if len(advertising_data) > 31:
                raise MgmtError("Tuya command does not fit in a legacy advertisement")
            if len(advertising_data) > features.max_advertising_length:
                raise MgmtError("advertising data exceeds the adapter limit")
            added = manager.add_advertisement(
                instance=self.instance,
                advertising_data=advertising_data,
                hold_seconds=self.hold_seconds,
                interval_ms=self.interval_ms,
                tx_power_dbm=self.tx_power_dbm,
                force_legacy=self.force_legacy,
            )
            if added != self.instance:
                raise MgmtError(f"kernel allocated unexpected advertising instance {added}")
            try:
                time.sleep(self.hold_seconds)
            finally:
                manager.remove_advertisement(self.instance)
