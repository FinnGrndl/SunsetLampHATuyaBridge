from __future__ import annotations

import pytest
from tuya_beacon_bridge.protocol import (
    ProtocolError,
    build_p2_frame,
    crc8,
    decode_datapoints,
    derive_beacon_key,
    dp_colour,
    dp_on_off,
    expected_on_air_advertisement,
    parse_p2_frame,
    validate_p2_frame,
    xxtea_decrypt,
    xxtea_encrypt,
)

LOCAL_KEY = b"YOURLOCALKEY1234"
BEACON_KEY = bytes.fromhex("00112233445566778899aabbccddeeff")


def test_xxtea_reference_vector() -> None:
    plaintext = bytes.fromhex("01110100000000000000000000000000")
    ciphertext = xxtea_encrypt(plaintext, LOCAL_KEY)
    assert ciphertext.hex() == "d8f9d9280212d431da3561c0536e133c"
    assert xxtea_decrypt(ciphertext, LOCAL_KEY) == plaintext


def test_p2_off_frame_round_trip_and_key_derivation() -> None:
    packet = build_p2_frame(
        source_id="1234",
        destination_id="0004",
        sequence=0x42,
        payload=dp_on_off(False),
        local_key=LOCAL_KEY,
        beacon_key=BEACON_KEY,
    )
    assert len(packet) == 26
    assert packet[:9].hex() == "0b12340004004205d6"
    assert validate_p2_frame(packet, BEACON_KEY)
    assert derive_beacon_key(packet, LOCAL_KEY, dp_on_off(False)) == BEACON_KEY

    frame = parse_p2_frame(
        packet,
        encryption_key=LOCAL_KEY,
        beacon_key=BEACON_KEY,
    )
    assert frame is not None
    assert frame.source_id == 0x1234
    assert frame.destination_id == 4
    assert frame.sequence == 0x42
    assert decode_datapoints(frame.payload) == {1: (1, b"\x00")}


def test_target_frame_uses_beacon_key_for_both_crypto_layers() -> None:
    packet = build_p2_frame(
        source_id="0004",
        destination_id="8000",
        sequence=0x0E06,
        payload=b"\x01",
        local_key=BEACON_KEY,
        beacon_key=BEACON_KEY,
        subcommand=2,
    )
    frame = parse_p2_frame(
        packet,
        encryption_key=BEACON_KEY,
        beacon_key=BEACON_KEY,
    )
    assert frame is not None
    assert frame.payload == b"\x01" + bytes(15)


def test_compact_datapoints_match_p2_format() -> None:
    assert dp_on_off(False).hex() == "011100"
    assert dp_on_off(True).hex() == "011101"
    assert dp_colour(0, 100, 100).hex() == "0b0400006464"
    assert crc8(dp_colour(0, 100, 100).ljust(16, b"\x00")) == 0x4B


def test_advertisement_layout_is_exactly_31_bytes() -> None:
    packet = build_p2_frame(
        source_id="7FFE",
        destination_id="0004",
        sequence=0,
        payload=dp_on_off(True),
        local_key=LOCAL_KEY,
        beacon_key=BEACON_KEY,
    )
    expected = expected_on_air_advertisement(packet)
    assert expected[:5] == b"\x02\x01\x06\x1b\x03"
    assert expected[5:] == packet
    assert len(expected) == 31


def test_rejects_invalid_keys_payloads_and_crc() -> None:
    with pytest.raises(ProtocolError):
        xxtea_encrypt(bytes(16), b"short")
    with pytest.raises(ProtocolError):
        dp_colour(361, 100, 100)
    packet = bytearray(
        build_p2_frame(
            source_id="7FFE",
            destination_id="0004",
            sequence=0,
            payload=dp_on_off(True),
            local_key=LOCAL_KEY,
            beacon_key=BEACON_KEY,
        )
    )
    packet[10] ^= 1
    assert not validate_p2_frame(bytes(packet), BEACON_KEY)
