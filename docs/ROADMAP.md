# GitHub-Projektplan

Empfohlenes GitHub Project: **Document Core Delivery**, Board-Ansichten nach Status und Milestone. Felder: Status, Priorität, Bereich, Aufwand, Milestone. Labels sind in `.github/labels.yml` beschrieben.

## M1 – Pipeline ohne KI (v0.1)

Ziel: synthetisches Textdokument Ende-zu-Ende vom Eingang zum Dateisystem-Connector. Enthalten: API, Hotfolder, OCR-Basis, Regeln, Quarantäne, Jobstore, Compose, Tests und Dokumentation.

## M2 – Robuste Verarbeitung (v0.2)

- PDF/Text-Layer und mehrseitige OCR
- PostgreSQL und atomare Delivery-Claims (umgesetzt)
- Worker/Queue, Lease-Recovery und Retry (umgesetzt)
- Worker-Metriken, kontrolliertes Shutdown und administrativer Retry
- Operator-Konsole für Übersicht, Vorschau, Review, Freigabe und Retry (MVP umgesetzt)
- Authentisierung, Rollenmodell und produktionsfähiger Audit-Trail
- Authentisierung, Audit-Events, Upload-Limits und Malware-Prüfung
- Review-API/-UI für Quarantäne
- Observability und Betriebsmetriken

## M3 – KI-Dokumenttyp-Vorschläge (v0.3)

- Provider-neutrales `DocumentClassifier`-Interface
- Vorschlag plus Konfidenz, Modell-/Promptversion und Evidenz
- Evaluation mit ausschließlich synthetischem/freigegebenem Datensatz
- Schwellwerte: automatisch, manuelle Prüfung, abweisen
- Regelbasierter Fallback und Feature Flag

## M4 – KI-gestützte Referenzzuordnung (v0.4)

- Kandidatenerkennung aus Dokumentinhalt
- Abgleich ausschließlich gegen autorisierte Referenzquellen
- keine automatische Zuordnung bei Mehrdeutigkeit
- Review, Audit, Qualitäts- und Datenschutztests

## M5 – Zielsystem-Pilot (v0.5)

- Integrationsweg mit einem ersten Zielsystem verifizieren
- Mapping-/Connector-Contract-Tests
- Sandbox-/Testmandant, Retry, Dead Letter und technische Quittung
- Pilot mit synthetischen Dokumenten, Security- und Datenschutzfreigabe

## Definition of Done

Akzeptanzkriterien erfüllt; Tests und Dokumentation aktualisiert; keine echten Fach- oder personenbezogenen Daten; Security-/Datenschutzauswirkungen bewertet; Migration und Rollback bei persistenter Änderung beschrieben.

Die Vorlagen unter `.github/ISSUE_TEMPLATE` machen aus jedem Roadmap-Punkt ein ausführbares Issue. Milestones werden nach Repository-Erstellung in GitHub mit obigen Namen und Zielen angelegt.
