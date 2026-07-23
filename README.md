# Document Core

Document Core ist eine erweiterbare, domänenneutrale Dokumenten-Pipeline: Dokumente kommen per Upload/API oder Hotfolder an, werden verarbeitet, geprüft und über generische Connectoren an Zielsysteme übergeben.

## Status

**Phase 1 – funktionierende Pipeline ohne KI.** Das MVP enthält:

- REST-API und Hotfolder als Eingangskanäle
- persistente Verwaltung mehrerer Hotfolder mit Dateimustern und Aktivstatus
- SHA-256-Deduplizierung mit transparenter Upload-Rückmeldung und persistente Job-Metadaten
- PostgreSQL-Persistenz mit Alembic-Migrationen und atomaren Statuswechseln
- asynchrone PostgreSQL-Queue mit separatem Worker, Lease-Recovery und Retry
- PDF-Text-Layer und seitenweiser OCR-Fallback mit Tesseract
- austauschbares `DocumentExtractor`-Interface mit integriertem Standardextraktor
- regelbasierte Dokumenttyp- und Metadatenextraktion
- provider-neutrale Dokumentklassifizierung mit Konfidenz, Evidenz und Modellversion
- Workflow-Regeln (Pflichtfelder, Quarantäne)
- generisches Connector-Interface, Dateisystem- und HTTP-Connector
- Multipart-Streaming, Retry-After, Fehlerklassen, Healthcheck und strukturierte HTTP-Quittungen
- persistente Zielsystemprofile mit Standardziel, Timeout und optionalem Bearer-Token
- verschlüsselte Connector-Secrets mit Startschutz, Redaction und Schlüsselrotation
- dokumenttypabhängige Ablageregeln und sichere Dateisystem-Pfadvorlagen
- persistentes Aktivitäts- und Zustellprotokoll mit Ziel, Versuch, Dauer und technischer Quittung
- automatisierte Tests und Docker Compose

KI wird erst hinter stabilen Interfaces ergänzt. Siehe [Roadmap](docs/ROADMAP.md).

## Schnellstart

```bash
cp .env.example .env
docker compose up --build
curl -F "file=@sample.txt" http://localhost:8000/v1/documents
curl http://localhost:8000/v1/jobs
```

Die Operator-Konsole ist anschließend unter `http://localhost:8000/` erreichbar. Sie bietet
Upload, Statusübersicht, Suche, Dokumentvorschau, Review, Freigabe, administrativen Retry
und einen workfloworientierten Arbeitsbereich für Übersicht, Prüfung, Dokumente,
Automatisierung und Einstellungen.
Die Dokumentdetailansicht zeigt zusätzlich eine chronologische Timeline aller relevanten
Verarbeitungs-, Review-, Retry- und Zustellereignisse. Zustellungen enthalten das verwendete
Zielsystem, die Ablageregel, den Versuch, die Dauer, die externe Referenz und mögliche Fehler.

Beim ersten Start wird `./data/hotfolder` als Standardkanal angelegt. Weitere Hotfolder
lassen sich in der Operator-Konsole unter **Eingangskanäle** konfigurieren. Alle Pfade sind
Unterordner von `./data`; erfolgreiche Ergebnisse landen strukturiert unter `./data/output`,
problematische Dokumente unter `./data/quarantine`.

Docker Compose startet API, Worker und PostgreSQL. Uploads antworten sofort mit
`202 Accepted` und Status `received`. Der Worker beansprucht Jobs atomar, erneuert während
der Verarbeitung seine Lease und wiederholt technische Fehler begrenzt. Der Upload-Hash
ist eindeutig; Jobs überleben Neustarts und parallele Freigaben werden auf genau einen
Connector-Aufruf begrenzt.

Identischer Dateiinhalt wird bereits vor dem Kopieren in die Inbox über SHA-256 erkannt.
Die Upload-Antwort verweist auf den vorhandenen Job und enthält `duplicate: true`; der
Mehrfachupload zählt neue Dokumente, Duplikate und Fehler getrennt.

Uploads und Hotfolder verwenden dieselbe Sicherheitsprüfung: Unterstützt werden PDF,
PNG, JPEG, TIFF sowie TXT, CSV, JSON und XML. Dateiendung und erkannter Inhalt müssen
zusammenpassen. Konfigurierbare Limits begrenzen Dateigröße, PDF-Seiten, Bildpixel und
OCR-Laufzeit; abgewiesene Dateien erzeugen keinen Job und keine Inbox-Arbeitskopie.
Optional kann dieselbe Eingangsstufe Dateien über einen ClamAV-Dienst prüfen. Der Scanner
ist standardmäßig deaktiviert und wird über `DOCUMENT_CORE_MALWARE_SCANNER=clamav` aktiviert.

Die Operator-Konsole ist durch Anmeldung und die Rollen `admin`, `operator` und `viewer`
geschützt. Admins erhalten den Navigationsbereich **Administration** mit der
**Benutzerverwaltung**. Der erste Admin wird beim leeren System aus den Bootstrap-Variablen
erzeugt; das Bootstrap-Passwort muss vor einem produktiven Start geändert werden.
Hash und Arbeitskopie entstehen in einem blockweisen Durchlauf über eine kurzlebige
Staging-Datei. Dadurch wird die Dateigröße nicht vollständig im Arbeitsspeicher gehalten.

Lokal:

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
pip install -e ".[dev]"
alembic upgrade head
uvicorn document_core.api:app --reload
pytest
```

## Beispielinhalt

```text
Bericht
Betreff: Beispielobjekt
Datum: 12.03.2026
Referenz: R-12345
```

## Dokumentation

- [Architektur](docs/ARCHITECTURE.md)
- [Betrieb und Konfiguration](docs/OPERATIONS.md)
- [Operator-Konsole](docs/FRONTEND.md)
- [Connectoren](docs/CONNECTORS.md)
- [Entwicklungs- und GitHub-Plan](docs/ROADMAP.md)
- [Entscheidungen (ADR)](docs/adr/0001-pipeline-first.md)
- [Beitragen](CONTRIBUTING.md)

## Continuous Integration

GitHub Actions prüft jeden Pull Request und jeden Push auf `main` reproduzierbar in vier
getrennten Jobs:

- Ruff, JavaScript-Syntax und die vollständige Unit-Test-Suite mit JUnit-Testbericht
- Repository-Vertrag gegen PostgreSQL 17
- vollständige Alembic-Migrationskette sowie Upgrade von Schema `0008` auf den aktuellen Stand
- reproduzierbarer Build des Docker-Images ohne Veröffentlichung

Die gleichen Kernprüfungen können lokal ausgeführt werden:

```bash
ruff check src tests migrations
node --check src/document_core/static/app.js
pytest -m "not integration"
docker compose exec document-core alembic current --check-heads
docker build -t document-core:local .
```

Der PostgreSQL-Integrationstest benötigt zusätzlich
`DOCUMENT_CORE_TEST_POSTGRES_URL` und eine zuvor mit `alembic upgrade head` migrierte Datenbank.

## API

- `POST /v1/documents` – Multipart-Upload (`202 Accepted`, asynchrone Verarbeitung)
- `GET /v1/jobs` – Jobs auflisten
- `GET /v1/jobs/stats` – Statuszahlen für das Dashboard
- `GET /v1/jobs/{job_id}` – Status und extrahierte Metadaten
- `GET /v1/jobs/{job_id}/events` – persistentes Aktivitäts- und Zustellprotokoll
- `GET /v1/jobs/{job_id}/content` – Dokumentvorschau oder Download
- `PATCH /v1/jobs/{job_id}/review` – quarantänisierten Job korrigieren
- `POST /v1/jobs/{job_id}/release` – geprüften Job freigeben
- `POST /v1/jobs/{job_id}/retry` – endgültig fehlgeschlagenen Job neu einplanen
- `DELETE /v1/jobs/{job_id}` – fehlgeschlagenen oder festhängenden Job samt Arbeitskopie löschen
- `GET|POST /v1/input-channels` – Eingangskanäle auflisten oder anlegen
- `PATCH|DELETE /v1/input-channels/{channel_id}` – Eingangskanal ändern oder löschen
- `GET|POST /v1/target-systems` – Zielsysteme auflisten oder anlegen
- `PATCH|DELETE /v1/target-systems/{target_id}` – Zielsystem konfigurieren oder löschen
- `GET|POST /v1/delivery-rules` – dokumenttypabhängige Ablageregeln verwalten
- `GET /health` – Healthcheck

OpenAPI/Swagger ist unter `http://localhost:8000/docs` verfügbar.

Bei PDFs wird vorhandener Text direkt übernommen. Nur Seiten ohne brauchbaren Text-Layer
werden gerendert und per OCR verarbeitet. `metadata.extraction_method`, `page_count` und
`ocr_pages` machen den verwendeten Weg nachvollziehbar.
