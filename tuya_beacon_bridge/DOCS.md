# Tuya Beacon Bridge documentation

This app is the Bluetooth transport for the **Tuya Beacon** Home Assistant
custom integration. It controls one supported Tuya P2 Beacon light using the
Bluetooth controller connected to the Home Assistant host.

## First-time setup

Configure the following required values:

- `target_mac`: the lamp's Bluetooth MAC address.
- `local_key`: the current 16-character Tuya Local Key.
- `api_token`: a random secret containing at least 24 characters. The same
  value is entered in the Home Assistant integration.

If you do not have the Local Key yet, follow the repository's
[Local Key guide](https://github.com/FinnGrndl/SunsetLampHATuyaBridge/blob/main/docs/LOCAL_KEY.md).
It explains how to create a Tuya cloud project, link the Smart Life account,
and read `result.local_key` through Tuya's API Explorer. The project is not
needed during normal bridge operation. A
[German version](https://github.com/FinnGrndl/SunsetLampHATuyaBridge/blob/main/docs/LOCAL_KEY.de.md)
is also available.

Leave `control_enabled` set to `false` and start the app. In Smart Life, send
one **OFF** command and one **ON** command while the phone and lamp are close to
Home Assistant. Order does not matter. The log first reports the observed
authenticated command and then `Provisioning complete` after the opposite
command arrives.

The two commands must independently derive the same Beacon Key and destination
node. The result is stored in the app's private `/data` directory with mode
`0600`; secrets and packet contents are not logged. Set `control_enabled` to
`true` and restart the app only after training completes.

If the lamp is paired again and receives a new Local Key, update `local_key`
and repeat the OFF/ON training. Provisioning saved for the old key is ignored.

## Integration setup

Install the **Tuya Beacon** custom integration from the same GitHub repository.
Use:

```text
Bridge URL: http://127.0.0.1:8099
API token:  the exact token configured above
```

## Options

- `source_id`: hexadecimal two-byte controller node ID. Change it if another
  controller on the same Beacon mesh already uses `7FFE`.
- `controller_index`: Bluetooth controller number (`0` means `hci0`).
- `scan_enabled`: enables shared BlueZ LE discovery. It must be enabled for
  automatic training and Smart Life state observation.
- `advertising_instance`: dedicated Linux Management advertising instance.
  The bridge refuses to overwrite it if another process already owns it.
- `advertising_interval_ms`: interval between radio transmissions. The bridge
  uses the interval-aware Linux Management API to send approximately three to
  four copies during the default command window. Keep the `100` ms default
  unless the adapter rejects it; older kernels automatically use a safe legacy
  fallback.
- `transmit_seconds`: duration of each command advertisement. The `0.35`
  default is responsive while still allowing several BLE transmissions.
- `listen_host` and `listen_port`: local API bind address. Keep the loopback
  default unless you understand the security impact.
- `log_level`: app logging verbosity.
- `target_node_id`, `key_derivation_off_packet`, and
  `key_derivation_on_packet`: optional migration/advanced fields for previously
  captured packets. Normally leave them unset and use automatic training.

## Permissions

`host_dbus` is used for a per-client BlueZ scan. `host_network`, `NET_ADMIN`,
and `NET_RAW` are required for the Linux HCI Management control channel.
AppArmor is disabled for that raw socket. The app does not request Docker,
host-PID, Home Assistant configuration, or Home Assistant API access.

The bridge never resets the controller, changes global controller settings, or
removes advertisements belonging to other instances.

## Troubleshooting

- **No training messages:** verify the MAC, enable scanning, move the phone and
  lamp near the Home Assistant Bluetooth adapter, then send OFF and ON again.
- **Only one command observed:** send the opposite state in Smart Life. Two
  independently matching commands are intentionally required.
- **Integration entity unavailable:** confirm training completed,
  `control_enabled` is `true`, and both sides use the same API token.
- **Commands are missed:** increase `transmit_seconds` to `0.5` or `0.7`.
- **Advertising instance occupied:** choose a free instance reported by the
  app log; do not reuse an active instance.
