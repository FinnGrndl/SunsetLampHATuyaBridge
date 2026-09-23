# Tuya Beacon for Home Assistant

Local control for Tuya P2/Beacon Mesh sunset lamps through the Bluetooth
adapter attached to Home Assistant. The project does not require an ESP32, a
Tuya gateway, a persistent cloud connection, or a GATT connection to the lamp.

The repository contains two cooperating parts:

- **Tuya Beacon Bridge**, a Home Assistant app that receives and transmits the
  lamp's legacy BLE advertisements.
- **Tuya Beacon**, a HACS-compatible custom integration that exposes a native
  RGB light entity in Home Assistant.

Power, RGB colour, and brightness are supported. The verified data model does
not expose colour temperature. State is optimistic because this P2 command
channel has no physical-LED acknowledgement.

## Requirements

- Home Assistant OS or a supervised Home Assistant installation with Apps.
- A local Bluetooth controller that supports LE advertising/peripheral mode.
- A Tuya lamp using the P2 Beacon protocol implemented here. It was developed
  and tested with product ID `zfakffqr`, model ID `f1nyuo`.
- The lamp's current 16-character Tuya Local Key and Bluetooth MAC address.
- Smart Life on a phone for the one-time automatic training step.

The Local Key can change after removing and pairing the lamp again. Follow the
step-by-step [Local Key guide](docs/LOCAL_KEY.md)
([Deutsch](docs/LOCAL_KEY.de.md)) to retrieve it from your own Tuya Developer
Platform project. Never post it in an issue or commit it to Git.

## Installation

Both installation steps use this repository URL:

```text
https://github.com/FinnGrndl/SunsetLampHATuyaBridge
```

### 1. Install and train the bridge app

1. In Home Assistant, open **Settings → Apps → App store → Repositories** and
   add the URL above.
2. Install **Tuya Beacon Bridge**.
3. If needed, retrieve the key using the
   [Local Key guide](docs/LOCAL_KEY.md)
   ([Deutsch](docs/LOCAL_KEY.de.md)). Open the app configuration and enter:

   ```yaml
   target_mac: "AA:BB:CC:DD:EE:FF"
   local_key: "0123456789ABCDEF"
   api_token: "use-a-random-string-with-at-least-24-characters"
   control_enabled: false
   ```

4. Start the app. With the phone near Home Assistant, switch the lamp **off**
   and then **on** in Smart Life. The app log will report each authenticated
   command and then `Provisioning complete`. No key material is logged.
5. Set `control_enabled: true`, save, and restart the app.

The bridge learns the mesh Beacon Key and target node from the two genuine
commands and stores them with mode `0600` in its private app data. It will
automatically request new training after the Local Key changes. Advanced users
can instead supply previously captured `key_derivation_off_packet` and
`key_derivation_on_packet` values.

### 2. Install the Home Assistant integration

1. In HACS, open **Integrations → ⋮ → Custom repositories**.
2. Add the same repository URL with category **Integration**.
3. Install **Tuya Beacon** and restart Home Assistant.
4. Open **Settings → Devices & services → Add integration → Tuya Beacon**.
5. Keep `http://127.0.0.1:8099` as the bridge URL and enter the same API token.

HACS installs only the custom integration. The bridge app is installed
separately because it needs controlled access to the host Bluetooth Management
socket.

## Responsiveness

Version 0.3 sends power and colour/brightness as one P2 advertisement instead
of two sequential advertisements. The default advertising window is also
reduced from 1.2 seconds to 0.35 seconds with an explicit 100 ms radio interval,
and the integration applies the bridge response immediately instead of making
a second HTTP request. An RGB change therefore takes one short radio window
rather than roughly 2.4 seconds while still transmitting several copies.

If commands are occasionally missed because of radio interference, increase
`transmit_seconds` to `0.5` or `0.7`. Values below the default trade reliability
for a smaller latency gain.

## Security and Bluetooth coexistence

- The Local Key, derived Beacon Key, API token, captures, plaintext, and
  ciphertext are never returned through diagnostics or written to logs.
- The API listens on loopback by default and requires a bearer token.
- The app reserves one configured advertising instance, refuses to overwrite
  an occupied instance, and removes only its own instance after transmission.
- Scanning uses a per-client BlueZ discovery session. The app never resets the
  Bluetooth controller or stops another client's discovery session.
- AppArmor is currently disabled because the raw HCI Management socket is
  required. Only `NET_ADMIN`, `NET_RAW`, host networking, and host D-Bus are
  requested; Docker, host PID, and Home Assistant API access are not.

See [SECURITY.md](SECURITY.md) for reporting issues and
[PROTOCOL_FINDINGS.md](PROTOCOL_FINDINGS.md) for the verified wire format.

## Known limitations

- One bridge app instance controls one lamp.
- Only the verified Tuya P2/Beacon wire format is supported; similarly named
  Tuya BLE products can use entirely different protocols.
- Power, RGB, and brightness are implemented. Scenes, music mode, timers, and
  colour temperature are not.
- Home Assistant Container/Core without Supervisor Apps is not supported by
  this host-Bluetooth bridge.

## Development

```bash
uv run --with pytest --with ruff --with dbus-fast pytest -q
uv run --with ruff ruff check .
python3 -m compileall -q tuya_beacon_bridge/app custom_components
```

Contributions and hardware reports are welcome. Please remove Local Keys, API
tokens, device IDs, MAC addresses, and raw encrypted captures before sharing
logs or diagnostics.

## License

MIT — see [LICENSE](LICENSE).
