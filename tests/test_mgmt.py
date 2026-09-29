from __future__ import annotations

import struct

from tuya_beacon_bridge.mgmt import (
    MGMT_ADV_FLAG_CONNECTABLE,
    MGMT_ADV_PARAM_INTERVAL,
    MGMT_ADV_PARAM_TIMEOUT,
    MGMT_ADV_PARAM_TX_POWER,
    MGMT_OP_ADD_ADVERTISING,
    MGMT_OP_ADD_EXT_ADV_DATA,
    MGMT_OP_ADD_EXT_ADV_PARAMS,
    MGMT_OP_REMOVE_ADVERTISING,
    ManagementSocket,
    MgmtError,
)
from tuya_beacon_bridge.protocol import expected_on_air_advertisement


class RecordingManagementSocket(ManagementSocket):
    def __init__(self) -> None:
        super().__init__(0)
        self.recorded: list[tuple[int, bytes]] = []

    def command(self, opcode: int, parameters: bytes = b"") -> bytes:
        self.recorded.append((opcode, parameters))
        if opcode == MGMT_OP_ADD_EXT_ADV_PARAMS:
            return struct.pack("<BbBB", 12, 0, 31, 31)
        if opcode in (MGMT_OP_ADD_EXT_ADV_DATA, MGMT_OP_REMOVE_ADVERTISING):
            return b"\x0c"
        raise AssertionError(f"unexpected opcode {opcode:#x}")


def test_explicit_interval_uses_legacy_pdu_extended_commands() -> None:
    manager = RecordingManagementSocket()
    packet = expected_on_air_advertisement(bytes(range(26)))

    assert manager.add_advertisement(
        instance=12,
        advertising_data=packet,
        hold_seconds=0.35,
        interval_ms=100,
        tx_power_dbm=7,
        force_legacy=False,
    ) == 12

    assert [opcode for opcode, _parameters in manager.recorded] == [
        MGMT_OP_ADD_EXT_ADV_PARAMS,
        MGMT_OP_ADD_EXT_ADV_DATA,
    ]
    _opcode, parameters = manager.recorded[0]
    instance, flags, duration, timeout, minimum, maximum, tx_power = struct.unpack(
        "<BIHHIIb", parameters
    )
    assert instance == 12
    assert flags == (
        MGMT_ADV_FLAG_CONNECTABLE
        | MGMT_ADV_PARAM_TIMEOUT
        | MGMT_ADV_PARAM_INTERVAL
        | MGMT_ADV_PARAM_TX_POWER
    )
    assert duration == 0
    assert timeout == 3
    assert minimum == maximum == 160  # 100 ms / 0.625 ms
    assert tx_power == 7

    _opcode, data = manager.recorded[1]
    assert data[:3] == bytes((12, 31, 0))
    assert data[3:] == packet


class LegacyFallbackSocket(ManagementSocket):
    def __init__(self) -> None:
        super().__init__(0)
        self.opcodes: list[int] = []

    def command(self, opcode: int, parameters: bytes = b"") -> bytes:
        self.opcodes.append(opcode)
        if opcode == MGMT_OP_ADD_EXT_ADV_PARAMS:
            raise MgmtError("not supported", status=0x0C)
        if opcode in (MGMT_OP_REMOVE_ADVERTISING, MGMT_OP_ADD_ADVERTISING):
            return b"\x0c"
        raise AssertionError(f"unexpected opcode {opcode:#x}")


def test_legacy_command_is_used_when_explicit_intervals_are_unsupported() -> None:
    manager = LegacyFallbackSocket()
    packet = expected_on_air_advertisement(bytes(range(26)))

    assert manager.add_advertisement(
        instance=12,
        advertising_data=packet,
        hold_seconds=1.2,
        interval_ms=100,
        tx_power_dbm=7,
        force_legacy=False,
    ) == 12
    assert manager.opcodes == [
        MGMT_OP_ADD_EXT_ADV_PARAMS,
        MGMT_OP_REMOVE_ADVERTISING,
        MGMT_OP_ADD_ADVERTISING,
    ]


def test_forced_legacy_skips_extended_commands() -> None:
    manager = LegacyFallbackSocket()
    packet = expected_on_air_advertisement(bytes(range(26)))

    assert manager.add_advertisement(
        instance=12,
        advertising_data=packet,
        hold_seconds=0.7,
        interval_ms=100,
        tx_power_dbm=7,
        force_legacy=True,
    ) == 12
    assert manager.opcodes == [MGMT_OP_ADD_ADVERTISING]
