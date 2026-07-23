# Speicherbereiche und Dateilebenszyklus

Document Core unterscheidet drei Speicherrollen. Lokal zeigen sie standardmäßig weiterhin
gemeinsam auf `data/`; produktiv können sie unabhängig als Docker-Mounts bereitgestellt werden.

| Rolle | Variable | Inhalt |
|---|---|---|
| Eingang | `DOCUMENT_CORE_INPUT_ROOT_DIR` | Hotfolder auf NAS, Scannerablage oder Fileserver |
| Arbeit | `DOCUMENT_CORE_WORK_DIR` | Inbox, manuelle Prüfung, fehlgeschlagene Jobs und optionale Abschlusskopien |
| Ziel | `DOCUMENT_CORE_DESTINATION_ROOT_DIR` | Dateisystem-Zielsysteme und strukturierte Archive |

`DOCUMENT_CORE_DATA_DIR` bleibt der kompatible Standard für alle drei Rollen, wenn keine
separate Variable gesetzt ist.

## Lebenszyklus

1. Der Hotfolder-Watcher übernimmt eine Datei blockweise in den Arbeitsbereich.
2. Erst nachdem Arbeitskopie und Job sicher gespeichert sind, wird die Quelldatei aus dem
   Hotfolder entfernt.
3. Unklare Dokumente werden aus `inbox/` nach `quarantine/` verschoben und bleiben dort für
   Vorschau und manuelle Prüfung verfügbar.
4. Nach erfolgreicher Zustellung greift `DOCUMENT_CORE_DELIVERED_FILE_POLICY`:

| Wert | Verhalten |
|---|---|
| `retain` | Arbeitskopie bleibt in `inbox/`; kompatibler Standard für lokale Tests |
| `archive` | Arbeitskopie wird nach `completed/` im Arbeitsbereich verschoben |
| `delete` | Arbeitskopie wird nach bestätigter Zustellung gelöscht |

Das Zielsystem verwaltet seine zugestellte Datei unabhängig von der Arbeitskopie. Ein Fehler
beim Aufräumen wiederholt deshalb keine bereits erfolgreiche externe Zustellung; der Zustand
`cleanup_failed` wird in den Job-Metadaten vermerkt.

## Beispiel mit NAS oder Fileserver

Netzwerkfreigaben werden zuerst auf dem Docker-Host eingebunden, beispielsweise unter
`/mnt/document-input` und `/mnt/document-archive`. Ein Compose-Override bindet sie anschließend
in API und Worker ein:

```yaml
services:
  document-core:
    environment:
      DOCUMENT_CORE_INPUT_ROOT_DIR: /sources
      DOCUMENT_CORE_WORK_DIR: /work
      DOCUMENT_CORE_DESTINATION_ROOT_DIR: /destinations
      DOCUMENT_CORE_DELIVERED_FILE_POLICY: delete
    volumes:
      - document-core-work:/work
      - /mnt/document-input:/sources
      - /mnt/document-archive:/destinations

  worker:
    environment:
      DOCUMENT_CORE_INPUT_ROOT_DIR: /sources
      DOCUMENT_CORE_WORK_DIR: /work
      DOCUMENT_CORE_DESTINATION_ROOT_DIR: /destinations
      DOCUMENT_CORE_DELIVERED_FILE_POLICY: delete
    volumes:
      - document-core-work:/work
      - /mnt/document-input:/sources
      - /mnt/document-archive:/destinations

volumes:
  document-core-work:
```

Unter Windows beziehungsweise WSL sollte die SMB-Freigabe stabil auf dem Host gemountet und
dieser Hostpfad an Docker übergeben werden. Zugangsdaten gehören in die Mount-Konfiguration
des Hosts, nicht in Document Core.

## Betrieb und Sicherung

- Der Arbeitsbereich muss persistent sein. Besonders `inbox/` und `quarantine/` dürfen bei
  einem Neustart nicht verloren gehen.
- Der Eingangsbereich ist eine Übergabezone, kein Archiv. Ein Absender sollte Dateien erst
  nach erfolgreicher Übergabe seinerseits löschen oder reproduzieren können.
- Für den Zielbereich gelten die Sicherungs- und Aufbewahrungsregeln des Zielsystems.
- API und Worker benötigen dieselben Pfade für Arbeit und Ziel, sonst können gespeicherte Jobs
  nach einem Containerwechsel nicht weiterverarbeitet werden.
- Mount-Verfügbarkeit und Schreibrechte müssen vor produktiven Eingängen überwacht werden.
