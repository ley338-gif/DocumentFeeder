# Mitwirken

1. Issue mit Akzeptanzkriterien anlegen.
2. Kleinen Branch erstellen (`feat/...`, `fix/...`, `docs/...`).
3. Tests und Dokumentation gemeinsam mit dem Code ändern.
4. `ruff check src tests migrations`, `node --check src/document_core/static/app.js` und
   `pytest -m "not integration"` ausführen.
5. Pull Request mit ausgefüllter Checkliste öffnen.

Die GitHub-Actions-Pipeline prüft zusätzlich PostgreSQL 17, die vollständige
Alembic-Migrationskette und den Docker-Build. Änderungen dürfen erst zusammengeführt werden,
wenn alle vier CI-Jobs erfolgreich sind.

Keine echten personenbezogenen oder vertraulichen Fachdaten in Tests, Logs, Issues oder Commits verwenden. Testdaten müssen vollständig synthetisch sein.
