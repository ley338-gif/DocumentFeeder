# Document Core

Document Core ist eine erweiterbare Dokumenten-Pipeline: Dokumente kommen per Upload/API oder Hotfolder an, werden verarbeitet, geprüft und über generische Connectoren an Zielsysteme (z. B. Medical Office) übergeben.

## Status

**Phase 1 – funktionierende Pipeline ohne KI.** Das MVP enthält:

- REST-API und Hotfolder als Eingangskanäle
- SHA-256-Deduplizierung und persistente Job-Metadaten
- optionale OCR mit Tesseract, Textdateien funktionieren ohne Zusatzsoftware
- regelbasierte Dokumenttyp- und Metadatenextraktion
- Workflow-Regeln (Pflichtfelder, Quarantäne)
- generisches Connector-Interface und Dateisystem-Connector
- automatisierte Tests und Docker Compose

KI wird erst hinter stabilen Interfaces ergänzt. Siehe [Roadmap](docs/ROADMAP.md).

## Schnellstart

```bash
cp .env.example .env
docker compose up --build
curl -F "file=@sample.txt" http://localhost:8000/v1/documents
curl http://localhost:8000/v1/jobs
```

Hotfolder: Dateien nach `./data/hotfolder` kopieren. Erfolgreiche Ergebnisse landen strukturiert unter `./data/output`, problematische Dokumente unter `./data/quarantine`.

Lokal:

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
pip install -e ".[dev]"
uvicorn document_core.api:app --reload
pytest
```

## Beispielinhalt

```text
Arztbrief
Patient: Erika Mustermann
Geburtsdatum: 12.03.1980
Fallnummer: F-12345
```

## Dokumentation

- [Architektur](docs/ARCHITECTURE.md)
- [Betrieb und Konfiguration](docs/OPERATIONS.md)
- [Connectoren](docs/CONNECTORS.md)
- [Entwicklungs- und GitHub-Plan](docs/ROADMAP.md)
- [Entscheidungen (ADR)](docs/adr/0001-pipeline-first.md)
- [Beitragen](CONTRIBUTING.md)

## API

- `POST /v1/documents` – Multipart-Upload
- `GET /v1/jobs` – Jobs auflisten
- `GET /v1/jobs/{job_id}` – Status und extrahierte Metadaten
- `GET /health` – Healthcheck

OpenAPI/Swagger ist unter `http://localhost:8000/docs` verfügbar.

