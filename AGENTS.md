# AGENTS.md — HABambulabStringing

Custom-Integration `bambu_stringing` für Home Assistant: Erkennung von Druckfehlern
(Stringing, Spaghetti, Warping, Layer-Shift) bei Bambu-Lab-Druckern per Mistral
Vision API. Details und Architektur: `SPEC.md`.

## Setup

- Python 3.13, `.venv/` enthält echtes Home Assistant 2026.2.3 (für Real-Tests).
- Git-Repository, Default-Branch `main`. GitHub-Remote: `rmrosk/HABambulabStringing`
  (public — HACS braucht das). `.venv/`, `__pycache__/`, `.pytest_cache/` werden
  nicht committed (`.gitignore`).
- Integration liegt in `custom_components/bambu_stringing/` (Version steht in
  `manifest.json`, aktuell 0.6.0). Mindest-HA-Version: 2026.3 (in `hacs.json`
  deklariert, getrieben durch das Integrations-Icon via `brand/`).

## Modell

- Default-Modell: `mistral-medium-latest` (`DEFAULT_MODEL` in `const.py`).
  Änderbar im Config Flow (`mistral_model`) — initial und in den Optionen.
- Vision-Client: `core/mistral.py` (Chat-Completions-API, `top_p: 1` wegen
  `temperature=0` / Reasoning-Modellen).
- Die `mistral-large-4`-Nennungen in Kommentaren (`core/mistral.py`,
  `runtime.py`) sind API-Beispiele (Reasoning/Timeouts), kein Verweis auf das
  Default — bei Modell-Wechsel nicht mitziehen.

## Release-Cycle

Details und Checkliste: `RELEASE.md`. Kurzfassung:

1. Version in `custom_components/bambu_stringing/manifest.json` erhöhen
   (SemVer — einzige Stelle, die die Version trägt).
2. Tests laufen lassen, committen, auf `main` pushen.
3. `.github/workflows/release.yml` erstellt automatisch Tag `v<version>` +
   GitHub-Release mit generierten Release Notes — nur wenn der Tag noch nicht
   existiert (Tag-Check verhindert Doppel-Releases). Kein Secret nötig, nutzt
   den `GITHUB_TOKEN` (`contents: write`). Manuell re-triggerbar via
   `workflow_dispatch`.
4. HACS liest die GitHub-Releases und bietet das Update an; HA zeigt es als
   `update.*`-Entity im Update-Cycle an.

Vor einem Release die statischen Badges in `README.md` aktualisieren
(`version-x.y.z`, `tests-N passed` — werden nicht automatisch gepflegt).

## Befehle

```bash
.venv/bin/python -m pytest -q          # kompletter Testlauf (pytest-asyncio, mode=auto)
.venv/bin/python -m pytest tests/test_decision.py -q   # einzelne Modul-Tests
```

Nach Testläufen `__pycache__`/`.pytest_cache` löschen (Projekt liegt in Nextcloud).

## Architektur-Overview

- `core/decision.py` — Entscheidungs-Engine: Thresholds, Streaks, Cooldowns,
  Hysterese. `print_failure`/`layer_shift_detected` erholen sich automatisch
  (Streak unter Threshold), `reset()` räumt Zustände, behält aber Mute.
- `core/mistral.py` — Vision-Client, `AnalysisResult` (Scores 0-100,
  `other_defects`), lenientes Parsen (fehlende Felder -> 0/()).
- `core/prompt.py` — Prompt v2.0 (Warping/Layer-Shift-Schema).
- `core/mjpeg.py`, `core/archive.py` — Frame-Grabber, Snapshot-Archiv
  (`/local/snapshots/<slug>/latest.jpg`).
- `runtime.py` — Orchestrierung, Push-Benachrichtigungen, Events, Reset-Service.
- `dashboard.py` — auto-generiertes Lovelace-Dashboard "3D-Druck" (sections
  view, 2-Spalten-Z-Grid, Header-Badges mit Druckfehler-Alarm).
- `config_flow.py`, `const.py` — Konfiguration; Schwellwerte in `const.py`
  pflegen (MIN/MAX/DEFAULT).

## Konventionen

- Sprache: Code/Identifier Englisch, UI-Strings, Benachrichtigungen und
  Log-Meldungen Deutsch.
- Übersetzungen bei neuen Optionen/Services in `translations/de.json`,
  `translations/en.json` UND `strings.json` (Kopie von en.json) synchron pflegen.
- Interne HA-APIs (lovelace, frontend) immer defensiv nutzen: lazy import
  innerhalb der Funktionen, try/except mit deutschen Log-Meldungen — das
  Dashboard darf das Setup nie brechen.
- Dashboard wird bei jedem (Re)Load vollständig regeneriert; manuelle Edits
  des Users werden überschrieben (by design).
- `DashboardsCollection` liegt NICHT in `hass.data` — eigene Instanz + manuelle
  Panel-Registrierung via `frontend.async_register_built_in_panel`.
- Nie `.venv/` oder API-Keys committen (`.gitignore` deckt beides ab;
  `benchmark/.env` ebenfalls ignoriert).

## Test-Fallstricke

- `tests/test_smoke_integration.py` installiert HA-Stubs (lovelace, frontend)
  via `sys.modules`/monkeypatch, BEVOR die Integration importiert wird —
  dashboard.py importiert deshalb lazy innerhalb der Funktionen.
- Smoke-Tests asserten die exakte Dashboard-Struktur (max_columns,
  grid_options, Badges) — bei Layout-Änderungen Tests UND
  `verify_real_ha.py`-Checks mit anpassen.

## Deployment (User-Aktion)

Über HACS aktualisiert sich die Integration automatisch über das veröffentlichte
Release. Manuell: `custom_components/bambu_stringing` auf den Pi kopieren, HA
neu starten / Entry neu laden — Dashboard regeneriert sich automatisch.
