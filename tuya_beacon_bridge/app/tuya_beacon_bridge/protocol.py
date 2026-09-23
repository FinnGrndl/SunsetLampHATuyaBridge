"""Tuya P2 Beacon protocol primitives.

Tuya P2 frames are carried as a 26-byte Complete List of 16-bit Service
UUIDs AD value. The 16-byte payload is XXTEA encrypted and then XOR masked
with the mesh-wide beacon key. Secrets are accepted but never logged here.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

PROTOCOL_NAME = "tuya-p2-beacon-xxtea-v2"
BLOCK_LENGTH = 16
P2_FRAME_LENGTH = 26
P2_DP_FRAME_TYPE = 0x0B
P2_DP_SUBCOMMAND = 0x05
DELTA = 0x9E3779B9


class ProtocolError(ValueError):
    """Raised when protocol input is malformed."""


@dataclass(frozen=True, slots=True)
class P2Frame:
    """A validated and decrypted P2 Beacon frame."""

    frame_type: int
    source_id: int
    destination_id: int
    sequence: int
    subcommand: int
    payload: bytes


def parse_local_key(value: str | bytes) -> bytes:
    """Validate and return the device local key as 16 literal ASCII bytes."""
    if isinstance(value, str):
        try:
            value = value.encode("ascii")
        except UnicodeEncodeError as err:
            raise ProtocolError("local key must contain ASCII only") from err
    if len(value) != BLOCK_LENGTH:
        raise ProtocolError("local key must be exactly 16 ASCII bytes")
    return bytes(value)


def parse_beacon_key(value: str | bytes) -> bytes:
    """Validate a 16-byte beacon key, accepting its 32-character hex form."""
    if isinstance(value, str):
        try:
            value = bytes.fromhex(value)
        except ValueError as err:
            raise ProtocolError("beacon key must be valid hexadecimal") from err
    if len(value) != BLOCK_LENGTH:
        raise ProtocolError("beacon key must be exactly 16 bytes")
    return bytes(value)


def parse_node_id(value: str | int, field: str = "node ID") -> int:
    """Parse Tuya's two-byte, big-endian hexadecimal node/source ID."""
    try:
        result = int(value, 16) if isinstance(value, str) else int(value)
    except ValueError as err:
        raise ProtocolError(f"{field} must be hexadecimal") from err
    if not 0 <= result <= 0xFFFF:
        raise ProtocolError(f"{field} must fit in 16 bits")
    return result


def _unpack_words(block: bytes) -> list[int]:
    if len(block) != BLOCK_LENGTH:
        raise ProtocolError("XXTEA block must be exactly 16 bytes")
    return list(struct.unpack(">4I", block))


def _pack_words(words: list[int]) -> bytes:
    return struct.pack(">4I", *(word & 0xFFFFFFFF for word in words))


def xxtea_encrypt(block: bytes, key: str | bytes) -> bytes:
    """Encrypt one 16-byte block using Tuya's big-endian XXTEA variant."""
    words = _unpack_words(block)
    key_words = _unpack_words(parse_local_key(key))
    total = 0
    z = words[3]
    for _ in range(19):
        total = (total + DELTA) & 0xFFFFFFFF
        e = (total >> 2) & 3
        for position in range(4):
            y = words[(position + 1) & 3]
            mixed = (
                (((z >> 5) ^ (y << 2)) + ((y >> 3) ^ (z << 4)))
                ^ ((total ^ y) + (key_words[(position & 3) ^ e] ^ z))
            )
            words[position] = (words[position] + mixed) & 0xFFFFFFFF
            z = words[position]
    return _pack_words(words)


def xxtea_decrypt(block: bytes, key: str | bytes) -> bytes:
    """Decrypt one 16-byte block using Tuya's big-endian XXTEA variant."""
    words = _unpack_words(block)
    key_words = _unpack_words(parse_local_key(key))
    total = (19 * DELTA) & 0xFFFFFFFF
    y = words[0]
    while total:
        e = (total >> 2) & 3
        for position in range(3, -1, -1):
            z = words[(position - 1) & 3]
            mixed = (
                (((z >> 5) ^ (y << 2)) + ((y >> 3) ^ (z << 4)))
                ^ ((total ^ y) + (key_words[(position & 3) ^ e] ^ z))
            )
            words[position] = (words[position] - mixed) & 0xFFFFFFFF
            y = words[position]
        total = (total - DELTA) & 0xFFFFFFFF
    return _pack_words(words)


def crc8(data: bytes) -> int:
    """CRC-8, polynomial 0x07, init 0, no reflection and no xor-out."""
    crc = 0
    for byte in data:
        crc ^= byte
        for _ in range(8):
            crc = ((crc << 1) ^ 0x07) & 0xFF if crc & 0x80 else (crc << 1) & 0xFF
    return crc


def _padded_payload(payload: bytes) -> bytes:
    if not 1 <= len(payload) <= BLOCK_LENGTH:
        raise ProtocolError("P2 payload must contain 1..16 bytes")
    return payload.ljust(BLOCK_LENGTH, b"\x00")


def _p2_outer_crc(packet_without_crc: bytes) -> int:
    """Tuya's P2 CRC over the unmasked frame (SDK's 0x8380 routine)."""
    if len(packet_without_crc) != 25:
        raise ProtocolError("P2 CRC input must be exactly 25 bytes")
    crc = 0
    data = bytes((packet_without_crc[0] & 0xFC,)) + packet_without_crc[1:]
    for byte in data:
        crc = (crc ^ (byte << 8)) & 0xFFFF
        for _ in range(8):
            if crc & 0x8000:
                crc ^= 0x8380
            crc = (crc << 1) & 0xFFFF
    return crc >> 8


def validate_p2_frame(packet: bytes, beacon_key: str | bytes) -> bool:
    """Unmask a frame and validate Tuya's outer P2 CRC."""
    if len(packet) != P2_FRAME_LENGTH:
        return False
    mask = parse_beacon_key(beacon_key)
    unmasked = bytearray(packet)
    unmasked[9:25] = bytes(
        left ^ right for left, right in zip(packet[9:25], mask, strict=True)
    )
    return _p2_outer_crc(bytes(unmasked[:25])) == packet[25]


def derive_beacon_key(packet: bytes, local_key: str | bytes, known_payload: bytes) -> bytes:
    """Recover the beacon XOR mask from one known outbound DP command."""
    if len(packet) != P2_FRAME_LENGTH:
        raise ProtocolError("key-derivation packet must be exactly 26 bytes")
    if packet[0] != P2_DP_FRAME_TYPE or packet[7] != P2_DP_SUBCOMMAND:
        raise ProtocolError("key-derivation packet is not a P2 DP command")
    plaintext = _padded_payload(known_payload)
    if crc8(plaintext) != packet[8]:
        raise ProtocolError("known payload does not match the packet payload CRC")
    encrypted = xxtea_encrypt(plaintext, parse_local_key(local_key))
    beacon_key = bytes(
        left ^ right for left, right in zip(packet[9:25], encrypted, strict=True)
    )
    if not validate_p2_frame(packet, beacon_key):
        raise ProtocolError("key-derivation packet has an invalid P2 CRC")
    return beacon_key


def build_p2_frame(
    *,
    source_id: str | int,
    destination_id: str | int,
    sequence: int,
    payload: bytes,
    local_key: str | bytes,
    beacon_key: str | bytes,
    subcommand: int = P2_DP_SUBCOMMAND,
) -> bytes:
    """Build one complete 26-byte outbound P2 DP frame."""
    if not 0 <= sequence <= 0xFFFF:
        raise ProtocolError("P2 sequence must fit in 16 bits")
    if not 0 <= subcommand <= 0xFF:
        raise ProtocolError("P2 subcommand must fit in one byte")
    plaintext = _padded_payload(payload)
    encrypted = xxtea_encrypt(plaintext, parse_local_key(local_key))
    mask = parse_beacon_key(beacon_key)
    protected = bytes(left ^ right for left, right in zip(encrypted, mask, strict=True))
    packet = bytearray(P2_FRAME_LENGTH)
    packet[0] = P2_DP_FRAME_TYPE
    packet[1:3] = parse_node_id(source_id, "source ID").to_bytes(2, "big")
    packet[3:5] = parse_node_id(destination_id, "destination ID").to_bytes(2, "big")
    packet[5:7] = sequence.to_bytes(2, "big")
    packet[7] = subcommand
    packet[8] = crc8(plaintext)
    packet[9:25] = encrypted
    packet[25] = _p2_outer_crc(bytes(packet[:25]))
    packet[9:25] = protected
    return bytes(packet)


def parse_p2_frame(
    packet: bytes,
    *,
    encryption_key: str | bytes,
    beacon_key: str | bytes,
) -> P2Frame | None:
    """Validate, unmask, and decrypt a P2 frame."""
    if not validate_p2_frame(packet, beacon_key):
        return None
    mask = parse_beacon_key(beacon_key)
    encrypted = bytes(left ^ right for left, right in zip(packet[9:25], mask, strict=True))
    plaintext = xxtea_decrypt(encrypted, encryption_key)
    if crc8(plaintext) != packet[8]:
        return None
    return P2Frame(
        frame_type=packet[0],
        source_id=int.from_bytes(packet[1:3], "big"),
        destination_id=int.from_bytes(packet[3:5], "big"),
        sequence=int.from_bytes(packet[5:7], "big"),
        subcommand=packet[7],
        payload=plaintext,
    )


def dp_on_off(on: bool) -> bytes:
    """DP 1: Boolean value in Tuya's compact P2 encoding."""
    return bytes((0x01, 0x11, int(on)))


def dp_colour(hue: int, saturation: int, value: int) -> bytes:
    """DP 11: raw HSV, H=0..360 and S/V=0..100."""
    if not 0 <= hue <= 360:
        raise ProtocolError("hue must be between 0 and 360")
    if not 0 <= saturation <= 100 or not 0 <= value <= 100:
        raise ProtocolError("saturation and value must be between 0 and 100")
    return bytes((0x0B, 0x04, hue >> 8, hue & 0xFF, saturation, value))


def decode_datapoints(payload: bytes) -> dict[int, tuple[int, bytes]]:
    """Decode compact P2 datapoints until zero padding begins."""
    result: dict[int, tuple[int, bytes]] = {}
    offset = 0
    while offset + 2 <= len(payload) and payload[offset] != 0:
        dp_id = payload[offset]
        descriptor = payload[offset + 1]
        dp_type = descriptor >> 4
        length = descriptor & 0x0F
        end = offset + 2 + length
        if length == 0 or end > len(payload):
            break
        result[dp_id] = (dp_type, payload[offset + 2 : end])
        offset = end
    return result


def expected_on_air_advertisement(packet: bytes) -> bytes:
    """Wrap one P2 frame in the exact 31-byte legacy advertisement."""
    if len(packet) != P2_FRAME_LENGTH:
        raise ProtocolError("P2 frame must be exactly 26 bytes")
    return b"\x02\x01\x06\x1b\x03" + packet
