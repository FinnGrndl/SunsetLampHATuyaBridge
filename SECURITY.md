# Security policy

Please report a suspected vulnerability privately through GitHub's security
advisory feature instead of opening a public issue.

Never include a Tuya Local Key, API token, derived Beacon Key, device ID, MAC
address, or complete encrypted capture in a report. Redact these values from
logs and screenshots. A Local Key should be considered compromised if it has
been published; remove and pair the device again to rotate it before reuse.

The local HTTP API is intended to remain bound to `127.0.0.1`. Exposing it to a
network broadens the trust boundary and is not a supported default.
