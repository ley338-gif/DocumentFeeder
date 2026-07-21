# Betrieb

## Verzeichnisse

| Pfad | Zweck |
|---|---|
| `data/hotfolder` | eingehende Dateien |
| `data/inbox` | unveränderte Arbeitskopien |
| `data/jobs` | persistierte Jobzustände |
| `data/output` | Dateisystem-Zielconnector |
| `data/quarantine` | fachlich unklare Dokumente |

## Konfiguration

Alle Einstellungen beginnen mit `DOCUMENT_CORE_`; siehe `.env.example`. `DOCUMENT_CORE_REQUIRE_PATIENT=true` erzwingt in Phase 1 ein per Regel erkanntes Feld `Patient:`.

## Sicherheit vor Produktivbetrieb

- TLS, Authentisierung und rollenbasierte Autorisierung ergänzen.
- Datenbank, Backups und Datenträger verschlüsseln.
- Inhalte und personenbezogene Metadaten niemals in Standardlogs schreiben.
- Audit-Trail, Löschfristen, Mandantentrennung und Auftragsverarbeitung klären.
- Viren-/Dateitypprüfung, Größenlimits und Ressourcenlimits ergänzen.
- Bedrohungsmodell sowie Datenschutz-Folgenabschätzung durchführen.

## Fehleranalyse

Jobstatus und `errors` über `/v1/jobs/{id}` prüfen. `quarantined` bedeutet fachlich unklar, `failed` technisch fehlgeschlagen. Die MVP-Version führt keinen automatischen Retry aus.

## PDF und OCR

PDF-Seiten mit mindestens 20 extrahierbaren Zeichen verwenden den Text-Layer. Seiten ohne
brauchbaren Text werden mit PDFium bei 2,5-facher Auflösung gerendert und mit Tesseract
(`DOCUMENT_CORE_TESSERACT_LANG`) verarbeitet. Die Job-Metadaten nennen Methode, Seitenzahl
und OCR-Seiten. Beschädigte oder leere PDFs erhalten den Status `failed`; lesbare, aber
fachlich unbekannte Dokumente werden quarantänisiert.
