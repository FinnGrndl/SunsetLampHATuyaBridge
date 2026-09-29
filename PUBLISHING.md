# Publishing checklist

The code is structured both as a Home Assistant App repository and as a HACS
integration repository. Complete this checklist before announcing a release.

## GitHub repository settings

1. Run a final secret scan before each release. The history was rebuilt before
   the first public release to remove the development lamp's MAC address. Do
   not commit Local Keys, API tokens, device IDs, UUIDs, MAC addresses, or raw
   encrypted captures in future changes.
2. Change the repository visibility from **Private** to **Public**. HACS only
   accepts public GitHub repositories.
3. Set this concise GitHub description:

   ```text
   Local Tuya P2 Beacon sunset-lamp control for Home Assistant over host Bluetooth
   ```

4. Add topics such as `home-assistant`, `hacs`, `tuya`, `bluetooth-low-energy`,
   `ble`, `home-assistant-app`, and `sunset-lamp`.
5. Keep GitHub Issues and private vulnerability reporting enabled.

## Validation and release

1. Push the prepared files to `main`.
2. Wait for the **Validate** workflow. It runs unit tests, Ruff, compilation,
   HACS validation, and Home Assistant hassfest.
3. Verify app installation from the public repository on Home Assistant OS and
   perform a real OFF, ON, RGB, and brightness test.
4. Create a GitHub release named after the app version (for example `v0.3.2`)
   from the matching tag. HACS can install directly from the default branch,
   but releases provide clearer version and rollback choices.

Users can then add the same public URL in both locations:

- **Settings → Apps → App store → Repositories** for the bridge app.
- **HACS → Integrations → Custom repositories** with category **Integration**
  for the custom integration.

Submitting the integration to HACS's default catalog is optional and should be
done only after reports from more than one hardware installation. The custom
repository path works without that submission.
