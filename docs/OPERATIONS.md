# Betrieb

## Verzeichnisse

| Pfad | Zweck |
|---|---|
| `data/hotfolder` | eingehende Dateien |
| `data/inbox` | unveränderte Arbeitskopien |
| `data/output` | Dateisystem-Zielconnector |
| `data/quarantine` | fachlich unklare Dokumente |

## Konfiguration

Alle Einstellungen beginnen mit `DOCUMENT_CORE_`; siehe `.env.example`. `DOCUMENT_CORE_REQUIRE_ROUTING_REFERENCE=true` erzwingt vor einer Auslieferung eine strukturierte Zielobjektreferenz.

`DOCUMENT_CORE_DATABASE_URL` konfiguriert die SQL-Datenbank. Docker Compose verwendet
PostgreSQL; ohne Konfiguration nutzt die lokale Entwicklung `data/document-core.db`
über SQLite. `DOCUMENT_CORE_DATABASE_AUTO_CREATE` ist lokal standardmäßig aktiv. Im
Compose-Betrieb ist es deaktiviert, weil Alembic das Schema vor dem API-Start migriert.

## Datenbank und Migrationen

```bash
alembic upgrade head
docker compose exec document-core alembic current
```

Die frühere JSON-Persistenz unter `data/jobs` wird nicht automatisch importiert. In einer
reinen Entwicklungsumgebung können diese alten JSON-Dateien archiviert werden; für reale
Daten ist vor dem Upgrade ein explizites Importskript erforderlich. Das PostgreSQL-Volume
bleibt bei `docker compose down` erhalten. `docker compose down -v` löscht es vollständig
und darf nur für einen bewusst bestätigten Entwicklungsreset verwendet werden.

## Sicherheit vor Produktivbetrieb

- TLS, Authentisierung und rollenbasierte Autorisierung ergänzen.
- Datenbank, Backups und Datenträger verschlüsseln.
- Inhalte und personenbezogene Metadaten niemals in Standardlogs schreiben.
- Audit-Trail, Löschfristen, Mandantentrennung und Auftragsverarbeitung klären.
- Viren-/Dateitypprüfung, Größenlimits und Ressourcenlimits ergänzen.
- Bedrohungsmodell sowie Datenschutz-Folgenabschätzung durchführen.

## Fehleranalyse

Jobstatus und `errors` über `/v1/jobs/{id}` prüfen. `quarantined` bedeutet fachlich unklar,
`delivering` eine aktuell beanspruchte Zustellung und `failed` technisch fehlgeschlagen.
Die MVP-Version führt noch keinen automatischen Retry aus.

Quarantänisierte Jobs werden über `PATCH /v1/jobs/{id}/review` korrigiert. Ein Review benötigt
Bearbeiter und Begründung; Dokumenttyp, Routing-Referenz und Metadaten sind optional. Erst
`POST /v1/jobs/{id}/release` validiert erneut und liefert aus. Bereits ausgelieferte Jobs
werden bei wiederholter Freigabe nicht erneut an den Connector gesendet.

## PDF und OCR

PDF-Seiten mit mindestens 20 extrahierbaren Zeichen verwenden den Text-Layer. Seiten ohne
brauchbaren Text werden mit PDFium bei 2,5-facher Auflösung gerendert und mit Tesseract
(`DOCUMENT_CORE_TESSERACT_LANG`) verarbeitet. Die Job-Metadaten nennen Methode, Seitenzahl
und OCR-Seiten. Beschädigte oder leere PDFs erhalten den Status `failed`; lesbare, aber
fachlich unbekannte Dokumente werden quarantänisiert.
