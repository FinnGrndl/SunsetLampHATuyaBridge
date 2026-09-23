# Verified P2 Beacon protocol

## Evidence

The target is a Tuya Beacon Mesh lighting product with DP 1 (power) and DP 11
(raw colour). Raw Linux Management events captured repeated Smart Life OFF, ON,
and red commands. The OFF and ON ciphertext was stable while the two-byte
sequence advanced. Red was independently repeated with the same protected
payload.

Tuya's Android Bluetooth SDK 6.7.3 was then inspected from Tuya's Maven
repository. Its P2 request builder and receiver match the capture byte for byte:

1. Pad the compact datapoint stream to 16 bytes.
2. Put CRC-8 of those 16 plaintext bytes in the frame header.
3. Encrypt the block with Tuya's big-endian XXTEA variant and the device local
   key.
4. XOR the encrypted block with the 16-byte mesh beacon key.
5. Compute Tuya's outer P2 CRC over the *unmasked* packet.
6. Advertise the resulting 26-byte frame as AD type `0x03`.

The OFF, ON, and red captures independently recover the same beacon key. Each
then decrypts to the expected datapoint and validates both CRC layers. A frame
advertised by the lamp also decrypts when the beacon key is used for both the
XXTEA and XOR layers, matching the SDK receiver.

## Wire format

The complete legacy advertising payload is exactly 31 bytes:

```text
02 01 06  1b 03  <26-byte P2 frame>
```

The P2 frame is:

| Offset | Length | Meaning |
|---:|---:|---|
| 0 | 1 | frame/type flags; DP request is `0x0b` |
| 1 | 2 | source ID, big-endian |
| 3 | 2 | destination node ID, big-endian |
| 5 | 2 | per-source sequence, big-endian |
| 7 | 1 | subcommand; DP write is `0x05` |
| 8 | 1 | CRC-8 of padded plaintext |
| 9 | 16 | XXTEA ciphertext XOR beacon key |
| 25 | 1 | outer P2 CRC calculated before XOR masking |

Compact datapoints use one descriptor byte: high nibble is the Tuya type and
low nibble is the value length.

| Function | DP | Plaintext prefix |
|---|---:|---|
| OFF | 1 bool | `01 11 00` |
| ON | 1 bool | `01 11 01` |
| HSV colour | 11 raw | `0b 04 HH HL SS VV` |

The Smart Life red capture decrypts to hue 0, saturation 100, value 100. This
also proves that brightness belongs in DP 11's value byte for this model. The
older `D007 + 128-bit UUID + controller-name` reference protocol is not used by
this lamp.

## Anti-replay and state

P2 uses a two-byte sequence scoped by source ID. Home Assistant has a dedicated
stable source ID and persists its own next sequence before transmission. It
does not reuse the phone's source ID or advance the phone's counter.

The lamp does not provide an application-level acknowledgement for these DP
writes. Home Assistant therefore marks the entity as assumed state. Authentic
phone DP frames can still be decrypted and applied to that assumed state.

## HAOS validation (2026-09-23)

- Home Assistant OS 18.3 / Core 2026.9.3
- Intel `hci0`, 12 supported advertising instances
- dedicated instance 12; no active instance overwritten
- raw Management observer and shared BlueZ discovery active
- exact P2 implementation passed the repository test suite
- live OFF followed by ON + red transmitted successfully through instance 12
- app restored to loopback-only API, automatic boot, control enabled

## Transport safety

The app uses `Add Advertising`/`Remove Advertising` from the Linux Bluetooth
Management API. It supplies the Flags structure explicitly, uses legacy
connectable advertising, sends no scan response, and removes only its own
instance. It never issues controller reset, global scan stop, `Set Advertising`,
or remove-all.
