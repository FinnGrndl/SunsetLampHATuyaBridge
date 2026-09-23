# Changelog

## 0.3.0

- Add automatic, local Beacon Key and target-node training from Smart Life OFF
  and ON commands.
- Combine power and colour/brightness into one P2 packet.
- Reduce the default advertising window from 1.2 seconds to 0.35 seconds.
- Request an explicit 100 ms advertising interval, with a legacy-kernel fallback.
- Add aarch64 support and public repository metadata.
- Keep existing manual OFF/ON capture configuration as a migration path.

## 0.2.1

- Implement the verified Tuya P2 Beacon XXTEA and XOR-mask protocol.
- Add safe shared scanning and dedicated advertising-instance handling.
