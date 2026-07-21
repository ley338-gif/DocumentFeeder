# Document Core

Document Core ist eine erweiterbare, domänenneutrale Dokumenten-Pipeline: Dokumente kommen per Upload/API oder Hotfolder an, werden verarbeitet, geprüft und über generische Connectoren an Zielsysteme übergeben.

## Status

**Phase 1 – funktionierende Pipeline ohne KI.** Das MVP enthält:

- REST-API und Hotfolder als Eingangskanäle
- SHA-256-Deduplizierung und persistente Job-Metadaten
- PDF-Text-Layer und seitenweiser OCR-Fallback mit Tesseract
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
Bericht
Betreff: Beispielobjekt
Datum: 12.03.2026
Referenz: R-12345
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
- `PATCH /v1/jobs/{job_id}/review` – quarantänisierten Job korrigieren
- `POST /v1/jobs/{job_id}/release` – geprüften Job freigeben
- `GET /health` – Healthcheck

OpenAPI/Swagger ist unter `http://localhost:8000/docs` verfügbar.

Bei PDFs wird vorhandener Text direkt übernommen. Nur Seiten ohne brauchbaren Text-Layer
werden gerendert und per OCR verarbeitet. `metadata.extraction_method`, `page_count` und
`ocr_pages` machen den verwendeten Weg nachvollziehbar.
