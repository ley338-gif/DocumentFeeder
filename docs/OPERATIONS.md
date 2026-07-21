# Betrieb

## Verzeichnisse

| Pfad | Zweck |
|---|---|
| `data/hotfolder` | Standard-Hotfolder; weitere Unterordner sind konfigurierbar |
| `data/inbox` | unveränderte Arbeitskopien |
| `data/output` | Dateisystem-Zielconnector |
| `data/quarantine` | fachlich unklare Dokumente |
| `data/mock-target` | Zustellungen des lokalen Mock-Zielsystems |

## Konfiguration

Alle Einstellungen beginnen mit `DOCUMENT_CORE_`; siehe `.env.example`. `DOCUMENT_CORE_REQUIRE_ROUTING_REFERENCE=true` erzwingt vor einer Auslieferung eine strukturierte Zielobjektreferenz.

`DOCUMENT_CORE_DATABASE_URL` konfiguriert die SQL-Datenbank. Docker Compose verwendet
PostgreSQL; ohne Konfiguration nutzt die lokale Entwicklung `data/document-core.db`
über SQLite. `DOCUMENT_CORE_DATABASE_AUTO_CREATE` ist lokal standardmäßig aktiv. Im
Compose-Betrieb ist es deaktiviert, weil Alembic das Schema vor dem API-Start migriert.

Queue und Worker werden über folgende Variablen gesteuert:

| Variable | Standard | Zweck |
|---|---:|---|
| `DOCUMENT_CORE_WORKER_POLL_INTERVAL` | `1` | Wartezeit ohne fälligen Job |
| `DOCUMENT_CORE_WORKER_LEASE_SECONDS` | `300` | Reservierungsdauer eines Jobs |
| `DOCUMENT_CORE_WORKER_MAX_ATTEMPTS` | `3` | maximale technische Versuche |
| `DOCUMENT_CORE_WORKER_RETRY_BASE_SECONDS` | `5` | Basis des exponentiellen Backoffs |

```bash
docker compose logs -f worker
docker compose restart worker
```

Ein Worker-Neustart verliert keine Jobs. Ein `processing`-Job kann nach Ablauf seiner Lease
erneut beansprucht werden. Connectoren müssen trotzdem den dokumentierten Idempotenzschlüssel
verwenden, da ein externer Aufruf und ein Datenbankcommit keine gemeinsame Transaktion bilden.

## Hotfolder verwalten

Hotfolder werden persistent in der Datenbank gespeichert und in der Operator-Konsole unter
**Eingangskanäle** verwaltet. Alternativ steht die API `/v1/input-channels` zur Verfügung.
`directory` ist immer relativ zu `DOCUMENT_CORE_DATA_DIR`; absolute Pfade und `..` sind
unzulässig. Der Dienst legt den konfigurierten Unterordner beim Speichern automatisch an.

Jeder aktive Kanal wird im durch `DOCUMENT_CORE_HOTFOLDER_INTERVAL` bestimmten Intervall
geprüft. Nur Dateien, die mindestens einem `patterns`-Eintrag entsprechen, werden übernommen.
Nach erfolgreicher Aufnahme wird die Quelldatei entfernt; die unveränderte Arbeitskopie liegt
anschließend unter `data/inbox`. `last_ingested_at` und `last_error` zeigen den Kanalzustand.
Deaktivieren oder Löschen eines Kanals verändert vorhandene Dateien im Hotfolder nicht.

## Zielsysteme verwalten

Zielsystemprofile werden unter **Zielsysteme** oder über `/v1/target-systems` verwaltet.
Beim ersten Start entsteht automatisch das Dateisystem-Standardziel. Ein neues HTTP-Ziel für
den Compose-Mock verwendet `http://mock-target:8090/documents`. Neue Jobs speichern die ID
des zu diesem Zeitpunkt aktiven Standardziels; ein späterer Standardwechsel verändert bereits
eingegangene Jobs nicht.

HTTP-Fehler werden wie andere technische Verarbeitungsfehler über die Worker-Queue erneut
versucht. `last_delivery_at` und `last_error` zeigen den letzten Zielzustand. Tokens liegen im
MVP verschlüsselt **nicht** vor, sondern lediglich zugriffsgeschützt in der Datenbank. Für
Produktion ist deshalb Secret-Manager- oder Envelope-Encryption-Anbindung verpflichtend.

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
`processing` einen vom Worker beanspruchten Job, `delivering` eine manuelle Zustellung und
`failed` einen nach allen Versuchen technisch fehlgeschlagenen Job. `attempt_count`,
`next_attempt_at`, `lease_expires_at`, `worker_id` und `last_error` erklären den Queue-Zustand.

Die Operator-Konsole ist unter `/`, die OpenAPI-Dokumentation unter `/docs` erreichbar.
Der Retry-Endpunkt und alle schreibenden UI-Aktionen sind im MVP nicht authentisiert und
dürfen nur in einer kontrollierten Entwicklungsumgebung zugänglich sein.

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
