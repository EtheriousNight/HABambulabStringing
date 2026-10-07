# AGENTS.md — HABambulabStringing

Custom-Integration `bambu_stringing` für Home Assistant: Erkennung von Druckfehlern
(Stringing, Spaghetti, Warping, Layer-Shift) bei Bambu-Lab-Druckern per Mistral
Vision API. Details und Architektur: `SPEC.md`.

## Setup

- Python 3.13, `.venv/` enthält echtes Home Assistant 2026.2.3 (für Real-Tests).
- Kein Git-Repository.
- Integration liegt in `custom_components/bambu_stringing/` (Version steht in
  `manifest.json`, aktuell 0.6.0). Mindest-HA-Version: 2026.3 (in `hacs.json`
  deklariert, getrieben durch das Integrations-Icon via `brand/`).

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

## Test-Fallstricke

- `tests/test_smoke_integration.py` installiert HA-Stubs (lovelace, frontend)
  via `sys.modules`/monkeypatch, BEVOR die Integration importiert wird —
  dashboard.py importiert deshalb lazy innerhalb der Funktionen.
- Smoke-Tests asserten die exakte Dashboard-Struktur (max_columns,
  grid_options, Badges) — bei Layout-Änderungen Tests UND
  `verify_real_ha.py`-Checks mit anpassen.

## Deployment (User-Aktion)

`custom_components/bambu_stringing` auf den Pi kopieren, HA neu starten /
Entry neu laden — Dashboard regeneriert sich automatisch.
