# Lizenzierung

Zusatzmodule werden über offline prüfbare, mit Ed25519 signierte Lizenzschlüssel aktiviert.
Document Core enthält ausschließlich den öffentlichen Prüfschlüssel. Der private Schlüssel
bleibt beim Hersteller und darf weder in dieses Repository noch auf eine Kundeninstallation
kopiert werden.

## Einmalig Signaturschlüssel erzeugen

```powershell
.\.venv\Scripts\python.exe tools\license_tool.py keygen `
  --private license-private.key `
  --public license-public.key
```

`license-private.key` muss anschließend in einen geschützten Secret Store verschoben werden.
Der Inhalt von `license-public.key` wird auf den Document-Core-Installationen konfiguriert:

```env
DOCUMENT_CORE_LICENSE_PUBLIC_KEY=<Inhalt von license-public.key>
```

Nach einer Änderung der Umgebungsvariable müssen API und Worker neu gestartet werden.

## Kundenlizenz ausstellen

Die Installation-ID steht unter **Administration → Lizenz**. Eine daran gebundene Lizenz wird
beispielsweise so ausgestellt:

```powershell
.\.venv\Scripts\python.exe tools\license_tool.py issue `
  --private C:\Sicher\license-private.key `
  --customer "Beispiel GmbH" `
  --feature connector.microsoft_graph `
  --expires 2027-12-31 `
  --installation-id "INSTALLATION-ID-AUS-DER-UI"
```

Die Ausgabe beginnt mit `DC1.` und wird dem Kunden als Lizenzschlüssel übergeben. Ein Admin fügt
sie unter **Administration → Lizenz** ein. Document Core prüft Signatur, Ablaufdatum und
Installationsbindung lokal und speichert anschließend den signierten Schlüssel in PostgreSQL.
Der Schlüssel enthält kein Passwort oder privates Signaturmaterial.

Die Lizenzprüfung erfolgt erneut bei jeder Connector-Verwendung. Eine abgelaufene, manipulierte
oder für eine andere Installation ausgestellte Lizenz schaltet das Modul nicht frei. Aktivierung
und Entfernung werden über den bestehenden Audit-Mechanismus protokolliert.

`DOCUMENT_CORE_CONNECTOR_ENTITLEMENTS` bleibt als einfache Entwicklungsfreischaltung erhalten.
Für ausgelieferte Installationen sollte diese Variable leer bleiben.
