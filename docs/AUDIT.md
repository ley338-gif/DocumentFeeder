# Systemprotokoll und Aufbewahrung

Das Systemprotokoll erfasst sicherheits- und betriebsrelevante Änderungen, Anmeldungen und
administrative Aktionen. Zugriff, Export und Aufbewahrung sind ausschließlich für Admins
freigegeben.

## Suche und Pagination

`GET /v1/audit-events` führt Suche, Ergebnisfilter, Zählung und Pagination vollständig in der
Datenbank aus. Unterstützte Parameter:

- `q`: Benutzer, Aktion, Ressourcentyp oder Ressourcen-ID
- `outcome`: `success` oder `failure`
- `limit`: 1 bis 200
- `offset`: Startposition

Damit lädt die API nicht mehr den vollständigen Auditbestand in den Anwendungsspeicher.

## CSV-Export

Admins können die aktuell gesetzten Such- und Ergebnisfilter als CSV exportieren. Der Export
wird in Blöcken aus PostgreSQL gelesen und enthält Zeit, Benutzer, Aktion, Ressource, Ergebnis,
Statuscode und die bereits redigierten technischen Details. Jeder Export erzeugt selbst einen
Audit-Eintrag.

## Aufbewahrung

Die Aufbewahrungsfrist ist unter **Administration → Systemprotokoll** zwischen 30 und 3650 Tagen
einstellbar. Ein Hintergrundlauf entfernt einmal täglich ältere Einträge. Zusätzlich kann ein
Admin die Bereinigung unmittelbar starten. Änderungen und manuelle Bereinigungen werden über
die bestehende Audit-Middleware protokolliert.

Standardwert: 365 Tage. Die Konfiguration wird in `system_settings` gespeichert und benötigt
keine zusätzliche Datenbankmigration.

## Manipulationserkennung

Jeder Eintrag enthält einen SHA-256-Hash über seine fachlichen Felder und den Hash des
vorherigen Eintrags. Eine fortlaufende Kettenposition erkennt zusätzlich gelöschte oder
umgeordnete Datensätze. Die Prüfung ist über **Integrität prüfen** abrufbar und läuft täglich
automatisch; ihr letzter Status erscheint zusätzlich im administrativen Systemstatus.

Bei einer regulären Aufbewahrungsbereinigung speichert Document Core den letzten entfernten
Hash und dessen Position als Kettenanker. Der erste verbleibende Eintrag muss weiterhin exakt
an diesen Anker anschließen. Damit bleibt die Kette auch nach zulässiger Löschung prüfbar.
Bestehende Einträge werden beim ersten Start nach Migration `0013` einmalig in chronologischer
Reihenfolge verkettet.

Die Hashkette ist manipulationserkennend, aber kein externer unveränderbarer Speicher. Ein
uneingeschränkter Datenbankadministrator könnte theoretisch Einträge und internen Anker
gemeinsam neu berechnen. Für höchste Compliance-Anforderungen bleibt deshalb das regelmäßige
Signieren oder externe Sichern des aktuellen Kettenkopfs ein späterer Härtungsschritt.
