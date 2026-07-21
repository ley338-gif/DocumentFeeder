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
- Eingangskanäle mit Name, Unterordner, Dateimustern und Aktivstatus verwalten
- Zielsysteme verwalten, Standardziel festlegen und im Review auswählen

## Eingangskanäle

Die Navigation **Eingangskanäle** zeigt alle persistent konfigurierten Hotfolder. Ein Kanal
verweist immer auf einen Unterordner des konfigurierten `data`-Verzeichnisses. Mehrere
Dateimuster werden kommagetrennt eingegeben, zum Beispiel `*.pdf, scan-*.tif`. Deaktivieren
pausiert die Abholung, ohne Konfiguration oder vorhandene Dateien zu löschen.

Beim ersten Start erzeugt der Dienst automatisch den Kanal `Standard-Hotfolder` für den
Unterordner `hotfolder`. Das Löschen eines Kanals entfernt nur den Datenbankeintrag; der
Ordner und darin liegende Dateien bleiben erhalten.

## Zielsysteme

Unter **Zielsysteme** werden Dateisystem- und HTTP-Ziele persistent konfiguriert. Genau ein
aktives Ziel ist Standard und wird neuen Jobs beim Eingang fest zugeordnet. Im manuellen
Review kann für quarantänisierte Dokumente ein anderes aktives Ziel gewählt werden.

Bearer-Tokens sind nach dem Speichern nicht mehr sichtbar. Die Oberfläche zeigt lediglich,
ob ein Token hinterlegt ist. Das Standardziel kann weder pausiert noch gelöscht werden;
zuerst muss ein anderes Ziel zum Standard gemacht werden.

## API-Verträge

`GET /v1/jobs` akzeptiert wiederholbare `status`-Parameter, `q`, `limit` und `offset` und
liefert `{items, total, limit, offset}`. `GET /v1/jobs/stats` liefert Zähler je Status.

`GET /v1/jobs/{id}/content` liefert den Inhalt inline. Mit `download=true` wird eine
Download-Disposition gesetzt. Der Server prüft, dass der gespeicherte Pfad innerhalb des
konfigurierten Inbox-Verzeichnisses liegt.

`POST /v1/jobs/{id}/retry` ist nur für `failed` erlaubt. Der Vorgang setzt Versuche und
technischen Fehlerzustand zurück und plant den Job erneut als `received` ein.

`GET`, `POST`, `PATCH` und `DELETE` unter `/v1/input-channels` bilden die Kanalverwaltung
ab. Absolute Pfade, Pfadwechsel mit `..` und Dateimuster mit Verzeichnisteilen werden mit
`422` abgelehnt. Doppelte Namen oder Ordner liefern `409`.

Die entsprechenden Operationen unter `/v1/target-systems` verwalten Zielprofile. HTTP-Ziele
benötigen eine gültige HTTP(S)-URL. Antworten verwenden `TargetSystemView` und enthalten
niemals das gespeicherte Token.

## Sicherheitsgrenze des MVP

Die Konsole besitzt noch keine Authentisierung oder Rollenprüfung. Review, Freigabe,
Dokumentdownload und Retry dürfen daher nicht öffentlich erreichbar gemacht werden. Vor
einem produktiven Einsatz sind mindestens Authentisierung, rollenbasierte Autorisierung,
CSRF-/Security-Header, Upload-Limits und ein belastbarer Audit-Trail erforderlich.

## Technischer Aufbau

Die statischen Dateien liegen unter `src/document_core/static` und werden als Python-
Package-Data ausgeliefert. Das Frontend verwendet browsernative APIs und benötigt keinen
separaten Buildprozess oder Node-Container.
