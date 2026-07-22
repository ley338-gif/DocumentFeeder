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
| `DOCUMENT_CORE_MAX_FILE_SIZE_BYTES` | `26214400` | maximale Dateigröße für Upload und Hotfolder |
| `DOCUMENT_CORE_MAX_PDF_PAGES` | `100` | maximale Seitenzahl pro PDF |
| `DOCUMENT_CORE_MAX_IMAGE_PIXELS` | `40000000` | maximale Pixelzahl pro Bild/OCR-Render |
| `DOCUMENT_CORE_OCR_TIMEOUT_SECONDS` | `60` | Zeitlimit je Tesseract-Aufruf |
| `DOCUMENT_CORE_MALWARE_SCANNER` | `disabled` | `disabled` oder `clamav` |
| `DOCUMENT_CORE_CLAMAV_HOST` | `clamav` | Hostname eines erreichbaren `clamd` |
| `DOCUMENT_CORE_CLAMAV_PORT` | `3310` | TCP-Port von `clamd` |
| `DOCUMENT_CORE_MALWARE_SCAN_TIMEOUT_SECONDS` | `30` | Verbindungs- und Antwortlimit |

```bash
docker compose logs -f worker
docker compose restart worker
```

Ein Worker-Neustart verliert keine Jobs. Ein `processing`-Job kann nach Ablauf seiner Lease
erneut beansprucht werden. Connectoren müssen trotzdem den dokumentierten Idempotenzschlüssel
verwenden, da ein externer Aufruf und ein Datenbankcommit keine gemeinsame Transaktion bilden.

## Hotfolder verwalten

Vor jedem Eingang prüft Document Core den SHA-256-Hash. Identischer Dateiinhalt verweist
auf den vorhandenen Job und wird mit `duplicate: true` sowie einem Event
`duplicate_detected` gekennzeichnet. Der Dateiname darf abweichen. Auch bei parallelen
Eingängen entfernt die Pipeline eine nicht benötigte zweite Arbeitskopie.
Hashing und Staging erfolgen blockweise mit `DOCUMENT_CORE_INGEST_CHUNK_SIZE_BYTES`
(Standard: 1 MiB). Verborgene `.ingest-*.tmp`-Dateien werden bei Duplikaten und Fehlern
entfernt. Der Datenbank-Constraint auf `sha256` sichert parallele Eingänge zusätzlich ab.
Während desselben Durchlaufs wird `DOCUMENT_CORE_MAX_FILE_SIZE_BYTES` erzwungen. Dateiendung
und Inhaltssignatur werden für PDF, PNG, JPEG und TIFF abgeglichen; Klartextformate müssen
UTF-8-lesbar sein. Nicht unterstützte oder falsch benannte Dateien bleiben im Hotfolder und
werden über `last_error` sichtbar. Beim HTTP-Upload antwortet die API mit `413` (zu groß)
oder `415` (nicht unterstützt/Endung passt nicht). Abgewiesene Dateien erzeugen keinen Job.

Mit `DOCUMENT_CORE_MALWARE_SCANNER=clamav` streamt Document Core die Staging-Datei über das
ClamAV-`INSTREAM`-Protokoll, ohne einen zusätzlichen vollständigen Datei-Buffer anzulegen.
Nur die Antwort `OK` wird akzeptiert. Ein Fund liefert HTTP `422`; ein nicht erreichbarer
oder unerwartet antwortender Scanner liefert `503`. In beiden Fällen entstehen weder Job
noch dauerhafte Inbox-Datei. Im Hotfolder bleibt die Quelldatei liegen und `last_error`
enthält die Ursache. Der Standard `disabled` ist ausschließlich für Entwicklung gedacht;
für produktive Eingänge muss ein gepflegter Scanner mit aktuellen Signaturen bereitstehen.

Für die lokale Erprobung enthält Compose einen optionalen ClamAV-Dienst. In `.env` muss
`DOCUMENT_CORE_MALWARE_SCANNER=clamav` gesetzt sein; danach wird das Profil gestartet:

```bash
docker compose --profile malware up -d
docker compose logs -f clamav
```

Der erste Start kann wegen des Signaturdownloads mehrere Minuten benötigen. Bis `clamd`
erreichbar ist, lehnt Document Core neue Eingänge mit `503` ab.

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

Dateisystemziele verwenden einen relativen Ablageordner innerhalb von
`DOCUMENT_CORE_DATA_DIR`. Pfadvorlagen unterstützen `{document_type}`, `{year}`, `{month}`,
`{supplier_name}`, `{job_id}` und `{reference}`. Absolute Pfade, `..` und unbekannte Platzhalter werden
abgelehnt. Externe Windows- oder Netzwerkordner werden als Docker-Volume unterhalb von
`/data` eingebunden und anschließend als relativer Zielordner konfiguriert.

Für `{year}` und `{month}` wertet Document Core zuerst `metadata.document_date` aus. Neben
`26.06.2026` werden Monatsnamen wie `Januar 2026` oder `15. Februar 2026` verstanden.
Lieferantennamen mit einer erkannten Rechtsform wie GmbH, AG oder KG werden bei Rechnungen als
`supplier_name` gespeichert. Leerzeichen und für Windows unzulässige Zeichen erscheinen im
Ordnernamen als Unterstriche; ohne Lieferant gilt `Unbekannter_Lieferant`.

Für lesbare Rechnungsdateien kann eine Regel beispielsweise
`rechnungen/{year}/{month}/{supplier_name}/{year}-{month}_{supplier_name}_{invoice_number}{extension}`
verwenden. Die Metadaten werden daneben als `<Dateiname>.metadata.json` gespeichert; die
Job-ID bleibt darin und in der Datenbank erhalten.

Ablageregeln unter `/v1/delivery-rules` überschreiben nach erfolgreicher Klassifikation das
Standardziel. Beispiel: `invoice` → `Rechnungsarchiv` →
`rechnungen/{year}/{month}/{supplier_name}/{year}-{month}_{supplier_name}_{invoice_number}{extension}`.

HTTP-Fehler werden wie andere technische Verarbeitungsfehler über die Worker-Queue erneut
versucht. `last_delivery_at` und `last_error` zeigen den letzten Zielzustand. Tokens liegen im
MVP verschlüsselt **nicht** vor, sondern lediglich zugriffsgeschützt in der Datenbank. Für
Produktion ist deshalb Secret-Manager- oder Envelope-Encryption-Anbindung verpflichtend.

## Aktivitäts- und Zustellprotokoll

`GET /v1/jobs/{job_id}/events` liefert die persistente Timeline eines Jobs. Sie umfasst
Eingang, Verarbeitungsbeginn, Quarantäne, Review, Retry sowie Beginn, Erfolg oder Fehler einer
Zustellung. Zustellereignisse nennen Zielsystem, Regel, Versuch, Zeitpunkte, Zielreferenz und
Fehlertext. Die Operator-Konsole zeigt dieselben Informationen in der Dokumentdetailansicht.

Das Ereignis `classification_completed` dokumentiert den vorgeschlagenen Dokumenttyp samt
Konfidenz, Evidenz, Provider und Modell- oder Regelversion. Dieselben Werte stehen unter
`metadata.classification`. Im aktuellen Stand steuert die Konfidenz noch keine automatische
Entscheidung; dafür gelten weiterhin ausschließlich die deterministischen Workflow-Regeln.

Beim administrativen Löschen eines noch nicht zugestellten Jobs werden auch dessen Events
gelöscht. Für produktive Compliance-Anforderungen muss vorab entschieden werden, ob Events
stattdessen getrennt und manipulationsgeschützt aufbewahrt werden müssen.

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

### Anmeldung und Benutzer

`DOCUMENT_CORE_AUTH_ENABLED=true` schützt UI und API durch eine HttpOnly-Sitzung. Beim ersten
Start einer leeren Datenbank wird der Admin aus `DOCUMENT_CORE_BOOTSTRAP_ADMIN_USERNAME` und
`DOCUMENT_CORE_BOOTSTRAP_ADMIN_PASSWORD` erzeugt. Das Beispielpasswort darf nicht produktiv
verwendet werden. Admins verwalten Benutzer, Rollen, Aktivstatus und Passwörter unter
**Administration → Benutzerverwaltung**. Viewer dürfen ausschließlich lesen; Operatoren
dürfen Dokumente bearbeiten, aber keine Benutzer-, Kanal-, Ziel- oder Regelkonfiguration
ändern. Sitzungen laufen nach `DOCUMENT_CORE_SESSION_TTL_HOURS` ab.

Für einen TLS-Betrieb muss das Session-Cookie im nächsten Härtungsschritt zusätzlich als
`Secure` konfiguriert und ein expliziter CSRF-Schutz ergänzt werden.

- TLS, Authentisierung und rollenbasierte Autorisierung ergänzen.
- Datenbank, Backups und Datenträger verschlüsseln.
- Inhalte und personenbezogene Metadaten niemals in Standardlogs schreiben.
- Audit-Trail, Löschfristen, Mandantentrennung und Auftragsverarbeitung klären.
- ClamAV-Signaturupdates und Scanner-Verfügbarkeit überwachen; Dateityp-, Größen-, Malware-
  und OCR-Ressourcenprüfungen sind technisch umgesetzt.
- Bedrohungsmodell sowie Datenschutz-Folgenabschätzung durchführen.

## Fehleranalyse

Jobstatus und `errors` über `/v1/jobs/{id}` prüfen. `quarantined` bedeutet fachlich unklar,
`processing` einen vom Worker beanspruchten Job, `delivering` eine manuelle Zustellung und
`failed` einen nach allen Versuchen technisch fehlgeschlagenen Job. `attempt_count`,
`next_attempt_at`, `lease_expires_at`, `worker_id` und `last_error` erklären den Queue-Zustand.

Fehlgeschlagene Jobs sowie Jobs in `processing` oder `quarantined` können administrativ über
die Dokumentdetailansicht oder `DELETE /v1/jobs/{id}` entfernt werden. Dabei werden der
Datenbankjob, die Inbox-Arbeitskopie und eine vorhandene Quarantänekopie dauerhaft gelöscht.
Bereits zugestellte Dokumente und Zielsystemdateien können über diesen Endpunkt nicht gelöscht
werden. Bei aktiver Verarbeitung verhindert der Store, dass der Worker den gelöschten Job
nachträglich wieder anlegt. Eine bereits begonnene externe Zustellung wird nicht gelöscht und
ist deshalb von der Aktion ausgenommen. Die Aktion ist im MVP nicht wiederherstellbar.

Die Operator-Konsole ist unter `/`, die OpenAPI-Dokumentation unter `/docs` erreichbar.
Der Retry-Endpunkt und alle schreibenden UI-Aktionen sind im MVP nicht authentisiert und
dürfen nur in einer kontrollierten Entwicklungsumgebung zugänglich sein.

Quarantänisierte Jobs werden über `PATCH /v1/jobs/{id}/review` korrigiert. Ein Review benötigt
Bearbeiter und Begründung; Dokumenttyp, Routing-Referenz und Metadaten sind optional. Erst
`POST /v1/jobs/{id}/release` validiert erneut und liefert aus. Bereits ausgelieferte Jobs
werden bei wiederholter Freigabe nicht erneut an den Connector gesendet.

## PDF und OCR

Verschlüsselte PDFs sowie PDFs oberhalb des Seitenlimits werden kontrolliert abgelehnt.
Bild- und PDF-OCR sind durch Pixel- und Laufzeitlimits geschützt.
Die automatisierte Blackbox-Suite deckt leere und abgeschnittene Dateien, verschlüsselte und
gedrehte Seiten, gemischte Text-/Scan-Dokumente, Seitenlimits sowie übergroße Renderflächen ab.
Sie verwendet ausschließlich zur Laufzeit erzeugte synthetische Dokumente.

Die Pipeline hängt ausschließlich vom `DocumentExtractor`-Vertrag ab. Standardmäßig wird
`DefaultDocumentExtractor` mit PDF-Text-Layer, seitenweisem Tesseract-Fallback und
Klartextunterstützung verwendet. Alternative Extraktoren werden beim Erzeugen der Pipeline
injiziert und müssen ein `ExtractionResult` mit Text, Methode, Seitenzahl, OCR-Seiten und
Warnungen liefern.

PDF-Seiten mit mindestens 20 extrahierbaren Zeichen verwenden den Text-Layer. Seiten ohne
brauchbaren Text werden mit PDFium bei 2,5-facher Auflösung gerendert und mit Tesseract
(`DOCUMENT_CORE_TESSERACT_LANG`) verarbeitet. Die Job-Metadaten nennen Methode, Seitenzahl
und OCR-Seiten. Beschädigte oder leere PDFs erhalten den Status `failed`; lesbare, aber
fachlich unbekannte Dokumente werden quarantänisiert.
Von PDF-Generatoren eingebettete Nullzeichen werden vor Klassifikation und Datenbankablage
entfernt, da PostgreSQL diese Zeichen in Textfeldern nicht unterstützt.
