# Tuya Local Key ermitteln

Die Bridge benötigt den **aktuellen, 16 Zeichen langen `local_key`** der Lampe.
Das ist weder das Smart-Life-Passwort noch das Client Secret, die Device ID,
UUID oder Product ID. Der Schlüssel wird einmalig über ein eigenes Tuya-Cloud-
Projekt abgerufen; im normalen Betrieb verwendet die Bridge die Cloud nicht.

> **Geheim halten:** Veröffentliche weder den Local Key noch das Client Secret
> in Issues, Screenshots, Logs, Chats oder Git-Repositories.

## 1. Cloud-Projekt anlegen

1. Melde dich auf der [Tuya Developer Platform](https://developer.tuya.com/) an.
2. Öffne **Cloud → Development** beziehungsweise in der neuen Oberfläche
   **Cloud → Project Management** und erstelle ein Cloud-Projekt.
3. Wähle als Development Method **Smart Home**.
4. Wähle das Rechenzentrum passend zur Region deines Smart-Life-Kontos. Die
   Region findest du in Smart Life unter **Ich → Einstellungen → Konto und
   Sicherheit → Region**. Ein falsches Rechenzentrum führt meist zu einer
   leeren Geräteliste.
5. Autorisiere mindestens **IoT Core** und **Smart Home Basic Service**. Tuya
   ändert gelegentlich Bezeichnungen und Gruppierung; das Projekt benötigt die
   Berechtigung zum Lesen von Geräteinformationen.

Siehe auch Tuyas offiziellen
[Konfigurationsassistenten](https://developer.tuya.com/en/docs/iot/Platform_Configuration_smarthome?id=Kamcgamwoevrx).

## 2. Smart-Life-Konto verknüpfen

1. Öffne im Projekt **Devices**.
2. Wähle **Link Tuya App Account → Add App Account** beziehungsweise
   **Link App Account**.
3. Scanne den angezeigten QR-Code mit Smart Life. Verwende das Konto, dem die
   Lampe gehört.
4. Bestätige die Freigabe in Smart Life und lasse **Automatic Link** aktiviert.
5. Öffne **Devices → All Devices**. Kopiere bei der Lampe die **Device ID**.
   Auch sie sollte nicht veröffentlicht werden; sie ist aber noch nicht der
   Local Key.

Der Ablauf ist in Tuyas Dokumentation
[Link Devices](https://developer.tuya.com/en/docs/iot/link-devices?id=Ka471nu1sfmkl)
beschrieben.

## 3. `local_key` im API Explorer auslesen

1. Öffne **Cloud → API Management → API Explorer**.
2. Wähle das soeben erstellte Projekt.
3. Suche nach **Get the device information** oder verwende den Endpoint:

   ```http
   GET /v1.0/iot-03/devices/{device_id}
   ```

4. Ersetze `{device_id}` durch die zuvor kopierte Device ID und sende die
   Anfrage ab.
5. Kopiere aus der JSON-Antwort ausschließlich `result.local_key`:

   ```json
   {
     "result": {
       "id": "REDACTED",
       "local_key": "0123456789ABCDEF"
     },
     "success": true
   }
   ```

Der Beispielschlüssel ist absichtlich erfunden. Feld und Endpoint stehen auch
in Tuyas offizieller
[API-Referenz](https://developer.tuya.com/en/docs/cloud/d00d20c097?id=Kag2xtiyewd3r).

Für diese Bridge muss der Wert exakt 16 ASCII-Zeichen lang sein. Trage ihn ohne
Anführungszeichen, Leerzeichen oder Zeilenumbruch als `local_key` in der App-
Konfiguration ein. Verwende dort nicht das Client Secret des Projekts.

## Fehlerbehebung

- **Lampe fehlt:** Region/Rechenzentrum prüfen und das App-Konto erneut
  verknüpfen.
- **Berechtigungsfehler:** IoT Core und Smart Home Basic Service für genau das
  ausgewählte Projekt autorisieren.
- **`local_key` fehlt:** Prüfen, ob die Lampe unter **All Devices** auftaucht
  und wirklich ihre Device ID verwendet wurde.
- **Schlüssel hat nicht 16 Zeichen:** Nicht auffüllen oder verändern, sondern
  Gerät und JSON-Feld erneut prüfen.
- **Nach erneutem Pairing ohne Funktion:** Beim Entfernen und erneuten Anlernen
  kann Tuya den Local Key austauschen. Key erneut abrufen, in der Bridge ändern
  und das Smart-Life-AUS/EIN-Training wiederholen.

Nach der Einrichtung kann die App-Konto-Verknüpfung im Tuya-Projekt bei Bedarf
wieder aufgehoben werden. Die Bridge selbst benötigt keine laufende Tuya-
Cloud-Verbindung.
