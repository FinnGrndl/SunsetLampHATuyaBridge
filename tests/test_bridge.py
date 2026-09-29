from __future__ import annotations

from pathlib import Path

from tuya_beacon_bridge.bridge import BridgeConfig, TuyaBeaconBridge
from tuya_beacon_bridge.protocol import (
    build_p2_frame,
    dp_on_off,
    parse_p2_frame,
)

LOCAL_KEY = b"YOURLOCALKEY1234"
BEACON_KEY = bytes.fromhex("00112233445566778899aabbccddeeff")


def _config(path: Path) -> BridgeConfig:
    return BridgeConfig(
        target_mac="02:00:00:00:00:04",
        local_key=LOCAL_KEY,
        beacon_key=BEACON_KEY,
        api_token="a" * 24,
        target_node_id=4,
        source_id=0x7FFE,
        controller_index=0,
        scan_enabled=True,
        advertising_instance=12,
        advertising_interval_ms=100,
        tx_power_dbm=7,
        force_legacy_advertising=False,
        transmit_seconds=0.01,
        control_enabled=True,
        listen_host="127.0.0.1",
        listen_port=8099,
        state_path=path,
        provisioning_path=path.with_name("provisioning.json"),
        confirmation_source="test_captures",
    )


def test_config_allows_automatic_training_without_captures(tmp_path: Path) -> None:
    config = BridgeConfig.from_options(
        {
            "target_mac": "02:00:00:00:00:04",
            "local_key": LOCAL_KEY.decode(),
            "api_token": "a" * 24,
        },
        tmp_path,
    )

    assert config.beacon_key is None
    assert config.target_node_id is None
    assert config.transmit_seconds == 0.35
    assert config.tx_power_dbm == 7
    assert config.force_legacy_advertising is False
    assert config.provisioning_path == tmp_path / "provisioning.json"


class RecordingAdvertiser:
    def __init__(self) -> None:
        self.emitted: list[bytes] = []

    def emit(self, advertising_data: bytes) -> None:
        self.emitted.append(advertising_data)


def test_rgb_command_is_emitted_and_persisted(tmp_path: Path) -> None:
    bridge = TuyaBeaconBridge(_config(tmp_path / "state.json"))
    advertiser = RecordingAdvertiser()
    bridge.advertiser = advertiser  # type: ignore[assignment]

    result = bridge.command(
        {"state": "on", "rgb_color": [0, 0, 255], "brightness": 128}
    )

    assert result["sequences"] == [0]
    assert result["light"] == {
        "on": True,
        "rgb_color": [0, 0, 255],
        "brightness": 128,
    }
    assert len(advertiser.emitted) == 1
    assert bridge.status()["command_counter"] == 0

    first = parse_p2_frame(
        advertiser.emitted[0][5:],
        encryption_key=LOCAL_KEY,
        beacon_key=BEACON_KEY,
    )
    assert first is not None
    assert first.payload[:9] == bytes.fromhex("0111010b0400f06432")

    off = bridge.command({"state": "off"})
    assert off["sequences"] == [1]
    assert off["light"]["on"] is False


def test_old_three_byte_sequence_is_discarded(tmp_path: Path) -> None:
    state_path = tmp_path / "state.json"
    state_path.write_text('{"sequence":70000}', encoding="utf-8")
    bridge = TuyaBeaconBridge(_config(state_path))
    assert bridge.status()["command_counter"] == -1


def test_automatic_off_on_training_is_persisted(tmp_path: Path) -> None:
    config = _config(tmp_path / "state.json")
    config = BridgeConfig(
        target_mac=config.target_mac,
        local_key=config.local_key,
        beacon_key=None,
        api_token=config.api_token,
        target_node_id=None,
        source_id=config.source_id,
        controller_index=config.controller_index,
        scan_enabled=config.scan_enabled,
        advertising_instance=config.advertising_instance,
        advertising_interval_ms=config.advertising_interval_ms,
        tx_power_dbm=config.tx_power_dbm,
        force_legacy_advertising=config.force_legacy_advertising,
        transmit_seconds=config.transmit_seconds,
        control_enabled=config.control_enabled,
        listen_host=config.listen_host,
        listen_port=config.listen_port,
        state_path=config.state_path,
        provisioning_path=config.provisioning_path,
    )
    bridge = TuyaBeaconBridge(config)

    for sequence, state in enumerate((False, True)):
        bridge.on_packet(
            build_p2_frame(
                source_id="1234",
                destination_id="0004",
                sequence=sequence,
                payload=dp_on_off(state),
                local_key=LOCAL_KEY,
                beacon_key=BEACON_KEY,
            ),
            "11:22:33:44:55:66",
        )

    status = bridge.status()
    assert status["protocol_confirmed"] is True
    assert status["target_node_id"] == "0004"
    assert status["provisioning"]["required"] is False
    assert config.provisioning_path.stat().st_mode & 0o777 == 0o600

    restored = TuyaBeaconBridge(config)
    assert restored.status()["protocol_confirmed"] is True
    assert restored.status()["confirmation_sources"] == ["automatic_off_on_training"]
