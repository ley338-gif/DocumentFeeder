# Document Core

Document Core ist eine erweiterbare, domänenneutrale Dokumenten-Pipeline: Dokumente kommen per Upload/API oder Hotfolder an, werden verarbeitet, geprüft und über generische Connectoren an Zielsysteme übergeben.

## Status

**Phase 1 – funktionierende Pipeline ohne KI.** Das MVP enthält:

- REST-API und Hotfolder als Eingangskanäle
- persistente Verwaltung mehrerer Hotfolder mit Dateimustern und Aktivstatus
- SHA-256-Deduplizierung und persistente Job-Metadaten
- PostgreSQL-Persistenz mit Alembic-Migrationen und atomaren Statuswechseln
- asynchrone PostgreSQL-Queue mit separatem Worker, Lease-Recovery und Retry
- PDF-Text-Layer und seitenweiser OCR-Fallback mit Tesseract
- regelbasierte Dokumenttyp- und Metadatenextraktion
- Workflow-Regeln (Pflichtfelder, Quarantäne)
- generisches Connector-Interface, Dateisystem- und HTTP-Connector
- persistente Zielsystemprofile mit Standardziel, Timeout und optionalem Bearer-Token
- dokumenttypabhängige Ablageregeln und sichere Dateisystem-Pfadvorlagen
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

Beim ersten Start wird `./data/hotfolder` als Standardkanal angelegt. Weitere Hotfolder
lassen sich in der Operator-Konsole unter **Eingangskanäle** konfigurieren. Alle Pfade sind
Unterordner von `./data`; erfolgreiche Ergebnisse landen strukturiert unter `./data/output`,
problematische Dokumente unter `./data/quarantine`.

Docker Compose startet API, Worker und PostgreSQL. Uploads antworten sofort mit
`202 Accepted` und Status `received`. Der Worker beansprucht Jobs atomar, erneuert während
der Verarbeitung seine Lease und wiederholt technische Fehler begrenzt. Der Upload-Hash
ist eindeutig; Jobs überleben Neustarts und parallele Freigaben werden auf genau einen
Connector-Aufruf begrenzt.

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

## API

- `POST /v1/documents` – Multipart-Upload (`202 Accepted`, asynchrone Verarbeitung)
- `GET /v1/jobs` – Jobs auflisten
- `GET /v1/jobs/stats` – Statuszahlen für das Dashboard
- `GET /v1/jobs/{job_id}` – Status und extrahierte Metadaten
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
