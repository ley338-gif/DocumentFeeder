# Operator-Konsole

Die integrierte Konsole unter `/` ist die erste domänenneutrale Bedienoberfläche für den
Document-Core. Sie wird vom selben FastAPI-Dienst ausgeliefert und verwendet ausschließlich
die dokumentierte `/v1`-API.

## Funktionsumfang

- Statusübersicht und Filter
- Suche nach Dateiname, Job-ID, Dokumenttyp und Routing-Referenz
- paginierte Jobliste
- Upload mit unmittelbarer Queue-Rückmeldung
- Detailansicht mit Queue-, Retry- und Metadateninformationen
- Inline-Vorschau und Download des Originaldokuments
- Review mit Dokumenttyp und strukturierter Routing-Referenz
- Freigabe quarantänisierter Dokumente
- administrativer Retry endgültig fehlgeschlagener Jobs
- automatische Aktualisierung im Vier-Sekunden-Intervall

## API-Verträge

`GET /v1/jobs` akzeptiert wiederholbare `status`-Parameter, `q`, `limit` und `offset` und
liefert `{items, total, limit, offset}`. `GET /v1/jobs/stats` liefert Zähler je Status.

`GET /v1/jobs/{id}/content` liefert den Inhalt inline. Mit `download=true` wird eine
Download-Disposition gesetzt. Der Server prüft, dass der gespeicherte Pfad innerhalb des
konfigurierten Inbox-Verzeichnisses liegt.

`POST /v1/jobs/{id}/retry` ist nur für `failed` erlaubt. Der Vorgang setzt Versuche und
technischen Fehlerzustand zurück und plant den Job erneut als `received` ein.

## Sicherheitsgrenze des MVP

Die Konsole besitzt noch keine Authentisierung oder Rollenprüfung. Review, Freigabe,
Dokumentdownload und Retry dürfen daher nicht öffentlich erreichbar gemacht werden. Vor
einem produktiven Einsatz sind mindestens Authentisierung, rollenbasierte Autorisierung,
CSRF-/Security-Header, Upload-Limits und ein belastbarer Audit-Trail erforderlich.

## Technischer Aufbau

Die statischen Dateien liegen unter `src/document_core/static` und werden als Python-
Package-Data ausgeliefert. Das Frontend verwendet browsernative APIs und benötigt keinen
separaten Buildprozess oder Node-Container.
