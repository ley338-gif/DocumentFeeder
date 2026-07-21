# Connector-Schnittstelle

`TargetConnector` trennt die domänenneutrale Pipeline vom Zielsystem. Ein Adapter implementiert:

```python
class TargetConnector(ABC):
    def deliver(self, job: DocumentJob) -> str: ...
    def healthcheck(self) -> bool: ...
```

`deliver` muss bei Wiederholung sicher sein (Idempotenzschlüssel: `job.id` oder `sha256`) und eine externe Referenz zurückgeben. Fehler dürfen nicht verschluckt werden; die Pipeline setzt den Job auf `failed`.

## Zielsystem-Adapter

Vor Implementierung muss die konkret verfügbare Integrationsform geklärt werden (API, Importordner oder Schnittstellenmodul). Der Adapter übernimmt Mapping, Authentisierung, Retry und technische Quittung; Klassifikation bleibt in der Processing Engine.

Minimaler Mappingvertrag:

| Document Core | Zielsystem |
|---|---|
| `job.id` | Idempotenz-/Importreferenz |
| `routing_reference` | eindeutige Zielobjektreferenz |
| `document_type` | Ziel-Dokumentklasse |
| Originaldatei | Dokumentinhalt |
| `created_at` | Eingangszeitpunkt |

Freitext allein reicht nicht für automatische Zuordnung. Produktiv sind eindeutige Routing-Referenzen und ein Review-Weg bei Mehrdeutigkeit erforderlich. `namespace`, `type` und `value` erlauben zielsystemspezifische Referenzen, ohne Fachbegriffe in den Kern zu übernehmen.
