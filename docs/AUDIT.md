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

## Noch offen

Die aktuelle Härtung verhindert unbegrenztes Wachstum und reduziert unnötige Datenhaltung.
Kryptografischer Manipulationsschutz – beispielsweise eine Hash-Verkettung mit extern
gesichertem Anker – bleibt ein separater Produktionsschritt. Datenbank-Admins können bestehende
Einträge derzeit technisch verändern; Rollen- und API-Schutz ersetzen keinen unveränderbaren
externen Audit-Speicher.
