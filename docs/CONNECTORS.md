# Connector-Schnittstelle

`TargetConnector` trennt die domänenneutrale Pipeline vom Zielsystem. Ein Adapter implementiert:

```python
class TargetConnector(ABC):
    def deliver(self, job: DocumentJob) -> DeliveryReceipt: ...
    def healthcheck(self) -> bool: ...
```

`deliver` muss bei Wiederholung sicher sein (Idempotenzschlüssel: `job.id` oder `sha256`) und
eine strukturierte Quittung mit externer Referenz zurückgeben. Vor manuellen Zustellungen
beansprucht ein atomarer Datenbankwechsel den Job exklusiv. Fehler dürfen nicht verschluckt
werden; die Pipeline setzt den Job abhängig von der Fehlerklasse auf Retry oder `failed`.

## Modul-Registry und Lizenzen

Connectoren werden zentral als `ConnectorModule` registriert. Ein Modul beschreibt seine stabile
ID, Anzeigename, Version, Fähigkeiten, Factory und optional ein Lizenzmerkmal. Die Pipeline enthält
keine Fallunterscheidung mehr für einzelne Zielsysteme, sondern bezieht die Implementierung über
die Registry.

`filesystem` und `http` gehören zum lizenzfreien Kern. Künftige Zusatzmodule verwenden zum
Beispiel `license_feature="connector.onedrive"`. Aktivierte Merkmale werden derzeit als
kommaseparierte Liste über `DOCUMENT_CORE_CONNECTOR_ENTITLEMENTS` eingelesen. Das ist bewusst nur
die Entitlement-Schnittstelle; eine signierte Lizenzdatei oder ein Lizenzdienst kann sie später
speisen, ohne Connectoren oder Pipeline zu ändern.

Die Lizenz wird serverseitig sowohl beim Speichern eines Zielsystems als auch unmittelbar vor
jeder Zustellung geprüft. Die UI-Anzeige allein ist keine Sicherheitsgrenze. Bei fehlender Lizenz
bleibt eine vorhandene Zielkonfiguration erhalten, eine Zustellung wird jedoch kontrolliert
abgewiesen. `GET /v1/connector-modules` liefert installierte Module, Fähigkeiten und Lizenzstatus.

## Schutz von Zugangsdaten

Felder aus `secret_fields` werden niemals über die Verwaltungs-API ausgegeben. Bearer-Tokens
werden vor dem Schreiben in PostgreSQL mit Fernet authentifiziert verschlüsselt; in der
Datenbank steht ausschließlich ein mit `enc:v1:` markierter Ciphertext. Der Schlüssel wird als
`DOCUMENT_CORE_CONNECTOR_SECRET_KEYS` oder produktiv als Docker-/Orchestrator-Secret über
`DOCUMENT_CORE_CONNECTOR_SECRET_KEYS_FILE` bereitgestellt und gehört weder in Git noch in Logs.

Die Variable akzeptiert für Rotation eine kommaseparierte Schlüsselliste. Der erste Schlüssel ist
der neue Primärschlüssel, weitere Einträge sind alte Entschlüsselungsschlüssel. Beim Start von API
und Worker werden bestehende Ciphertexte auf den Primärschlüssel rotiert. Danach kann der alte
Schlüssel entfernt werden. Bestehende Klartext-Tokens werden beim ersten Start mit konfiguriertem
Schlüssel automatisch migriert. Fehlt der Schlüssel oder passt keiner der Schlüssel, verweigert
der Prozess den Start, bevor Dokumente verarbeitet werden.

Ein Schlüssel wird lokal so erzeugt:

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Bekannte Secretwerte werden zusätzlich zentral aus technischen Fehlern und Audit-Details
entfernt. Die Redaction ergänzt die Verschlüsselung, ersetzt aber keine restriktive
Protokollierung externer Antworten.

Minimaler Registrierungsvertrag:

```python
registry.register(ConnectorModule(
    id="example",
    name="Example DMS",
    version="1.0",
    capabilities=("document", "metadata"),
    license_feature="connector.example",
    factory=ExampleConnector,
))
```

## Implementierte Connectoren

Der Dateisystem-Connector schreibt Dokument und `metadata.json` strukturiert unter
dem konfigurierten Ablageordner. Die Standardvorlage lautet
`{document_type}/{job_id}`. Verfügbar sind außerdem `{year}`, `{month}`, `{supplier_name}`
und `{reference}`. Jahr und Monat stammen vorrangig aus dem erkannten Dokumentdatum;
unterstützt werden numerische Daten sowie deutsche Monatsnamen. Ohne Dokumentdatum gilt das
Eingangsdatum. Dynamische Pfadwerte werden als sichere Ordnernamen normalisiert, wobei
Leerzeichen zu Unterstrichen werden.

Eine Vorlage darf auch einen vollständigen Dateinamen enthalten. Dafür stehen
`{invoice_number}` und `{extension}` zur Verfügung. Rechnungsnummern werden im Dateinamen
auf Buchstaben und Ziffern reduziert, beispielsweise
`{year}-{month}_{supplier_name}_{invoice_number}{extension}`.
Aufgelöste Pfade müssen innerhalb des Zielordners bleiben. Der generische HTTP-Connector sendet
das Dokument per `multipart/form-data`: `metadata` enthält ein JSON-Objekt, `file` streamt den
Originalinhalt in Blöcken. Dadurch entstehen weder Base64-Aufschlag noch eine vollständige
Dokumentkopie im Arbeitsspeicher. `Idempotency-Key` enthält immer die Job-ID; ein optionaler
Bearer-Token wird als `Authorization`-Header übertragen und von der Verwaltungs-API niemals
zurückgegeben. Das Multipart-Format folgt [RFC 7578](https://www.rfc-editor.org/info/rfc7578/).

Die Zielantwort darf leer sein oder muss `application/json` mit `reference`, `id` und optional
`status` liefern. Alternativ verwendet der Connector den `Location`-Header. Antwortgrößen sind
pro Ziel begrenzt. Die technische Quittung mit Connector, HTTP-Status, Content-Type, Referenz und
freigegebenen Antwortfeldern wird unter `metadata.delivery_receipt` und im Zustellereignis
persistiert.

Netzwerkfehler sowie HTTP `408`, `425`, `429`, `500`, `502`, `503` und `504` gelten als temporär.
Bei `429` und `503` wird `Retry-After` als Sekundenwert oder HTTP-Datum ausgewertet und als
Mindestwartezeit für den nächsten Worker-Versuch übernommen. Andere `4xx`-Antworten gelten als
permanent und werden nicht wiederholt. Eine optionale `healthcheck_url` wird mit demselben Token,
Timeout und Antwortlimit geprüft, ohne ein Dokument zu übertragen.

Docker Compose enthält unter `http://localhost:8090` ein ausschließlich für Entwicklung
bestimmtes Mock-Ziel. Zustellungen an `http://mock-target:8090/documents` werden unter
`data/mock-target/{job.id}` gespeichert.

## Microsoft OneDrive / SharePoint

Das Modul `microsoft_graph` übergibt Dokumente an ein Drive in OneDrive for Business oder
eine SharePoint-Dokumentbibliothek. Es ist mit
`DOCUMENT_CORE_CONNECTOR_ENTITLEMENTS=connector.microsoft_graph` freizuschalten und verwendet
den OAuth-2.0-Client-Credentials-Flow einer Microsoft-Entra-App. Benötigt werden Mandant-ID,
Client-ID, Client-Secret, Drive-ID und ein bereits vorhandener Zielordner. Das Client-Secret
wird verschlüsselt gespeichert und nie über GET-Endpunkte ausgegeben.

Dateien bis 10 MiB werden direkt übertragen. Größere Dateien verwenden eine Graph-Upload-Session
mit sequenziellen 10-MiB-Blöcken; die Blockgröße ist ein Vielfaches von 320 KiB. Die
vorautorisierte Upload-URL erhält bewusst keinen zusätzlichen Authorization-Header. Diese
Vorgaben entsprechen dem
[Microsoft-Graph-Vertrag für Upload-Sessions](https://learn.microsoft.com/en-us/graph/api/driveitem-createuploadsession?view=graph-rest-1.0).
Der Remote-Dateiname beginnt mit der Job-ID und bleibt dadurch bei einem erneuten Zustellversuch
stabil. Die Quittung enthält Drive-ID, Zielpfad, DriveItem-ID und – falls vorhanden – die
Web-URL.

Die Entra-App benötigt Schreibzugriff auf das konfigurierte Drive. Microsoft nennt für
Anwendungsberechtigungen `Sites.ReadWrite.All`; produktiv sollte der Zugriff nach Möglichkeit
weiter auf ausgewählte Sites beschränkt werden. Der Healthcheck bezieht ein App-Token und liest
das konfigurierte Drive, ohne ein Dokument anzulegen.

## Zielsystem-Adapter

Vor Implementierung eines konkreten Adapters muss die verfügbare Integrationsform geklärt
werden. Der Adapter übernimmt Mapping, Authentisierung und technische Quittung;
Klassifikation und Queue-Retry bleiben in Document Core.

Minimaler Mappingvertrag:

| Document Core | Zielsystem |
|---|---|
| `job.id` | Idempotenz-/Importreferenz |
| `routing_reference` | eindeutige Zielobjektreferenz |
| `document_type` | Ziel-Dokumentklasse |
| Originaldatei | Dokumentinhalt |
| `created_at` | Eingangszeitpunkt |

Freitext allein reicht nicht für automatische Zuordnung. Produktiv sind eindeutige Routing-Referenzen und ein Review-Weg bei Mehrdeutigkeit erforderlich. `namespace`, `type` und `value` erlauben zielsystemspezifische Referenzen, ohne Fachbegriffe in den Kern zu übernehmen.
