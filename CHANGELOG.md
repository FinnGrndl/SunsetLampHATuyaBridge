# Changelog

## 0.3.2

- Add optional per-advertisement transmit power (`tx_power_dbm`, default
  `7` dBm) and a `force_legacy_advertising` compatibility mode to the bridge.
- Align the integration version with the bridge app.

## 0.3.0

- Add a Home Assistant App repository and HACS custom-repository installation
  path with public metadata, documentation, translations, validation, and
  brand assets.
- Add automatic mesh-key and target-node training from one Smart Life OFF and
  ON command.
- Send power plus RGB/brightness in one BLE packet and reduce the default
  advertising window to 0.35 seconds with an explicit 100 ms interval.
- Update Home Assistant state directly from command responses.

## 0.2.1

- First hardware-verified Tuya P2 Beacon implementation.
