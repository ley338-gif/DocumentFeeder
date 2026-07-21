# ADR 0001: Deterministische Pipeline vor KI

- Status: angenommen
- Datum: 2026-07-21

## Kontext

Transport, Nachvollziehbarkeit und Zielsystemübergabe müssen unabhängig von Modellqualität funktionieren. Patienten- und Dokumentzuordnung haben hohe fachliche Risiken.

## Entscheidung

Version 0.1 verwendet explizite Regeln und Quarantäne. KI wird später über austauschbare Interfaces als nachvollziehbarer Vorschlagsdienst ergänzt. Unsichere Ergebnisse benötigen menschliche Prüfung.

## Folgen

Das MVP ist früher testbar und bietet eine messbare Baseline. KI-Features müssen Konfidenz, Modellversion und Evaluation nachweisen; sie umgehen nie Workflow-Regeln oder Auditierung.

