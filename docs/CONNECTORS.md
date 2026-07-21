# Connector-Schnittstelle

`TargetConnector` trennt die domänenneutrale Pipeline vom Zielsystem. Ein Adapter implementiert:

```python
class TargetConnector(ABC):
    def deliver(self, job: DocumentJob) -> str: ...
    def healthcheck(self) -> bool: ...
```

`deliver` muss bei Wiederholung sicher sein (Idempotenzschlüssel: `job.id` oder `sha256`) und eine externe Referenz zurückgeben. Vor manuellen Zustellungen beansprucht ein atomarer Datenbankwechsel den Job exklusiv. Fehler dürfen nicht verschluckt werden; die Pipeline setzt den Job auf `failed`.

## Implementierte Connectoren

Der Dateisystem-Connector schreibt Dokument und `metadata.json` strukturiert unter
dem konfigurierten Ablageordner. Die Standardvorlage lautet
`{document_type}/{job_id}`. Verfügbar sind außerdem `{year}`, `{month}` und `{reference}`.
Aufgelöste Pfade müssen innerhalb des Zielordners bleiben. Der generische HTTP-Connector sendet ein JSON-Paket
per `POST`. `Idempotency-Key` enthält immer die Job-ID; ein optionaler Bearer-Token wird als
`Authorization`-Header übertragen und von der Verwaltungs-API niemals zurückgegeben.

Das HTTP-Paket enthält `job_id`, `filename`, `content_type`, den Base64-kodierten Inhalt,
`document_type`, `routing_reference` und `metadata`. Die Zielantwort sollte `reference` oder
`id` als JSON liefern. Alternativ verwendet der Connector den `Location`-Header.

Docker Compose enthält unter `http://localhost:8090` ein ausschließlich für Entwicklung
bestimmtes Mock-Ziel. Zustellungen an `http://mock-target:8090/documents` werden unter
`data/mock-target/{job.id}` gespeichert.

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
