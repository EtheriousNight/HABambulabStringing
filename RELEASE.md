# Release-Cycle

Dokumentation, wie eine neue Version der Integration veröffentlicht wird.
Der Ablauf ist automatisiert: Sobald die Version in `main` erhöht und gepusht
wird, erstellt GitHub Actions automatisch einen Tag und ein GitHub-Release.
HACS bzw. Home Assistant zeigen das Update anschließend an.

## Versionsnummer

Die Versionsnummer steht an genau einer Stelle:

`custom_components/bambu_stringing/manifest.json` → `"version": "0.6.0"`

SemVer-Schema (`MAJOR.MINOR.PATCH`):

- **PATCH** — Bugfixes, keine Verhaltensänderung
- **MINOR** — neue Features, abwärtskompatibel
- **MAJOR** — Breaking Changes (z. B. neue Pflichtfelder in der Konfiguration)

## Ablauf

1. Änderungen lokal committen
2. Tests laufen lassen: `.venv/bin/python -m pytest -q`
3. Version in `manifest.json` erhöhen
4. Commit + Push auf `main`:

   ```bash
   git add -A
   git commit -m "…"
   git push
   ```

5. Fertig — der Rest läuft automatisch (siehe unten)

## Was der Workflow automatisch macht

`.github/workflows/release.yml` läuft bei jedem Push auf `main` (und manuell
über *Actions → Release → Run workflow*):

1. Liest `version` aus `custom_components/bambu_stringing/manifest.json`
2. Prüft, ob der Tag `v<version>` bereits auf GitHub existiert
3. Falls nein: erstellt den Tag, pusht ihn und legt ein GitHub-Release mit
   automatisch generierten Release Notes an (`gh release create --generate-notes`)

Der Workflow verwendet ausschließlich den von GitHub Actions bereitgestellten
`GITHUB_TOKEN` (`permissions: contents: write`) — es müssen keine Secrets
eingerichtet werden.

**Ohne Versionsänderung passiert nichts.** Der Tag-Check verhindert, dass
erneute Pushes ohne Versions-Bump doppelte Releases erzeugen.

## Sichtbarkeit in HACS / Home Assistant

- **HACS** liest die GitHub-Releases des Repos und bietet die neueste Version
  als Update an (Voraussetzung: Repo als *Custom Repository*, Kategorie
  *Integration*, hinzugefügt; das Repo muss public sein)
- **Home Assistant** zeigt HACS-Updates als `update.*`-Entities an und im
  Update-Cycle unter *Einstellungen → System → Updates*
- Beim **ersten Push** (`git push -u origin main`) wird automatisch die
  aktuelle Version (z. B. `v0.6.0`) als erstes Release veröffentlicht

## Checkliste vor einem Release

- [ ] Tests grün: `.venv/bin/python -m pytest -q`
- [ ] Version in `custom_components/bambu_stringing/manifest.json` erhöht
- [ ] Statische Badges in `README.md` aktualisiert (`version-0.6.0`,
      `tests-86 passed` — werden nicht automatisch gepflegt)
- [ ] Commit-Message beschreibt die Änderung
- [ ] Nach dem Push prüfen: GitHub → *Actions* (Workflow grün?) und *Releases*
      (neuer Tag `v<version>` vorhanden?)

## Manuelles Nachholen / Edge Cases

- **Workflow fehlgeschlagen?** GitHub → *Actions → Release → Run workflow*
  erneut auslösen.
- **Tag existiert, Release wurde gelöscht?** Der Tag-Check verhindert ein
  erneutes Anlegen. Tag lokal und remote löschen, dann Workflow erneut laufen
  lassen:

  ```bash
  git tag -d v0.6.0
  git push origin :refs/tags/v0.6.0
  ```

## Deployment auf den Pi

Über HACS aktualisiert sich die Integration automatisch. Manuell:

```bash
scp -r custom_components/bambu_stringing pi@homeassistant:/config/custom_components/
# HA neu starten oder Entry neu laden — Dashboard regeneriert sich automatisch
```
