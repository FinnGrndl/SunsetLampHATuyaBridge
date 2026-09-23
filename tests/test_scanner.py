from __future__ import annotations

from tuya_beacon_bridge.protocol import build_p2_frame, dp_on_off
from tuya_beacon_bridge.scanner import BlueZObserver

LOCAL_KEY = b"YOURLOCALKEY1234"
BEACON_KEY = bytes.fromhex("00112233445566778899aabbccddeeff")


def _eir(packet: bytes) -> bytes:
    return b"\x02\x01\x06\x1b\x03" + packet


def test_raw_management_advertisements_are_forwarded_and_deduplicated() -> None:
    frames: list[tuple[bytes, str]] = []
    observer = BlueZObserver(
        "02:00:00:00:00:04",
        lambda packet, address: frames.append((packet, address)),
    )

    controller = build_p2_frame(
        source_id="1234",
        destination_id="0004",
        sequence=0x42,
        payload=dp_on_off(False),
        local_key=LOCAL_KEY,
        beacon_key=BEACON_KEY,
    )
    observer._inspect_raw_advertisement("11:22:33:44:55:66", -40, 0, _eir(controller))
    observer._inspect_raw_advertisement("11:22:33:44:55:66", -40, 0, _eir(controller))

    target = build_p2_frame(
        source_id="0004",
        destination_id="8000",
        sequence=0x0E06,
        payload=b"\x01",
        local_key=BEACON_KEY,
        beacon_key=BEACON_KEY,
        subcommand=2,
    )
    observer._inspect_raw_advertisement(
        "02:00:00:00:00:04", -60, 0, _eir(target)
    )

    assert frames == [
        (controller, "11:22:33:44:55:66"),
        (target, "02:00:00:00:00:04"),
    ]


def test_all_structural_p2_packets_are_forwarded_for_provisioning() -> None:
    frames: list[object] = []
    observer = BlueZObserver(
        "02:00:00:00:00:04",
        lambda packet, address: frames.append((packet, address)),
    )
    unrelated = build_p2_frame(
        source_id="1111",
        destination_id="2222",
        sequence=1,
        payload=dp_on_off(True),
        local_key=LOCAL_KEY,
        beacon_key=BEACON_KEY,
    )
    observer._inspect_raw_advertisement("11:11:11:11:11:11", -50, 0, _eir(unrelated))
    assert frames == [(unrelated, "11:11:11:11:11:11")]
