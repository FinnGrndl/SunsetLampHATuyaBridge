# Getting the Tuya Local Key

The bridge needs the **current 16-character `local_key`** for the lamp. This is
not your Smart Life password, Tuya project Client Secret, device ID, UUID, or
product ID. The key is obtained from your own Tuya cloud project once; the
bridge does not contact Tuya during normal operation.

> **Keep it secret.** A Local Key grants local cryptographic access to the
> device. Do not paste it into an issue, screenshot, log, chat, or public Git
> repository. Keep the Tuya project Client Secret private as well.

## 1. Create a Tuya cloud project

1. Sign in to the [Tuya Developer Platform](https://developer.tuya.com/).
2. Open **Cloud → Development** (in newer layouts this can appear as
   **Cloud → Project Management**) and create a cloud project.
3. Select **Smart Home** as the development method.
4. Select the data center that serves the region of your Smart Life account.
   In Smart Life, the region is shown under **Me → Settings → Account and
   Security → Region**. A wrong data center is the most common reason for an
   empty device list.
5. Authorize at least **IoT Core** and **Smart Home Basic Service** when the
   platform asks for cloud services. Tuya occasionally changes the names and
   grouping of these services; the project needs permission to read device
   information.

Tuya's official project setup guide is available under
[Configuration Wizard of Smart Home PaaS](https://developer.tuya.com/en/docs/iot/Platform_Configuration_smarthome?id=Kamcgamwoevrx).

## 2. Link the Smart Life account

1. Open the project and select **Devices**.
2. Choose **Link Tuya App Account → Add App Account**. In newer layouts this
   can be named **Link App Account**.
3. Scan the displayed QR code with the Smart Life app while signed in to the
   account that owns the lamp.
4. Confirm the authorization in Smart Life and keep **Automatic Link** enabled.
5. Return to **Devices → All Devices**. The lamp should now be listed. Copy its
   **Device ID**; this identifier is also confidential and is not the Local Key.

These are the steps Tuya documents in
[Link Devices](https://developer.tuya.com/en/docs/iot/link-devices?id=Ka471nu1sfmkl).

## 3. Read `local_key` with API Explorer

1. Open **Cloud → API Management → API Explorer**.
2. Select the cloud project created above.
3. Find the device-information operation. Depending on the current UI, search
   for **Get the device information** or enter this endpoint:

   ```http
   GET /v1.0/iot-03/devices/{device_id}
   ```

4. Replace `{device_id}` with the Device ID copied from **All Devices**, then
   submit the request.
5. In the JSON response, copy only `result.local_key`:

   ```json
   {
     "result": {
       "id": "REDACTED",
       "local_key": "0123456789ABCDEF"
     },
     "success": true
   }
   ```

The example value above is intentionally fake. Tuya describes the same field
and endpoint in its official
[Get the device information API reference](https://developer.tuya.com/en/docs/cloud/d00d20c097?id=Kag2xtiyewd3r).

For this bridge the returned value must contain exactly 16 ASCII characters.
Paste it into the app's `local_key` option without quotes, spaces, or a trailing
newline. Do not use the project's Client Secret.

## Troubleshooting

- **The lamp is missing:** verify that the project data center matches the
  Smart Life account region, then unlink and link the app account again.
- **The API returns a permission error:** authorize IoT Core/Smart Home Basic
  Service for the selected project and retry with that same project selected
  in API Explorer.
- **`local_key` is absent:** confirm that the device appears under the
  project's **All Devices** tab and that the Device ID belongs to the lamp, not
  to a gateway or another device.
- **The key is not 16 characters:** do not pad or modify it. Recheck the JSON
  field and device selection. This implementation supports the verified
  16-byte P2 lamp key format only.
- **The bridge stopped working after pairing again:** removing and re-adding a
  Tuya device can rotate its Local Key. Repeat this procedure, update the app
  option, and perform the Smart Life OFF/ON training again.

After setup, the Tuya cloud project is not used by the bridge. You can revoke
the linked-app authorization if desired; keep a secure offline record of the
Local Key in case the app needs to be reconfigured.
