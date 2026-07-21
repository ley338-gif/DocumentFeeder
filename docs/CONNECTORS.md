# Connector-Schnittstelle

`TargetConnector` trennt die Pipeline vom Zielsystem. Ein Adapter implementiert:

```python
class TargetConnector(ABC):
    def deliver(self, job: DocumentJob) -> str: ...
    def healthcheck(self) -> bool: ...
```

`deliver` muss bei Wiederholung sicher sein (Idempotenzschlüssel: `job.id` oder `sha256`) und eine externe Referenz zurückgeben. Fehler dürfen nicht verschluckt werden; die Pipeline setzt den Job auf `failed`.

## Medical-Office-Adapter (geplant)

Vor Implementierung muss die konkret verfügbare Integrationsform geklärt werden (Hersteller-API, Importordner, Schnittstellenmodul). Der Adapter übernimmt Mapping, Authentisierung, Retry und technische Quittung; fachliche Klassifikation bleibt in der Processing Engine.

Minimaler Mappingvertrag:

| Document Core | Zielsystem |
|---|---|
| `job.id` | Idempotenz-/Importreferenz |
| `metadata.patient_id` | eindeutige Patientenreferenz |
| `document_type` | Ziel-Dokumentklasse |
| Originaldatei | Dokumentinhalt |
| `created_at` | Eingangszeitpunkt |

Patientenname allein reicht nicht für automatische Zuordnung. Produktiv sind eindeutige Identifikatoren und ein Review-Weg bei Mehrdeutigkeit erforderlich.

