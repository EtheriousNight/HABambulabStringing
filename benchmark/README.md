# Mistral Vision Benchmark – 3D-Druck Fehlererkennung

Testet verschiedene Mistral Vision Modelle auf ihre Fähigkeit, 3D-Druck-Fehler
(Stringing, Spaghetti, Warping, Layer-Shift) in Kammerbildern zu erkennen.

## Setup

```bash
cd benchmark
pip install aiohttp

# API-Key als Umgebungsvariable (keine .env Datei nötig):
export MISTRAL_API_KEY=sk-...
```

## Ausführen

```bash
# Alle Modelle testen (Default)
python3 run_benchmark.py

# API-Key als Argument
python3 run_benchmark.py --api-key sk-...

# Nur bestimmte Modelle
python3 run_benchmark.py --models mistral-large-latest mistral-small-latest

# Mehrere Anfragen parallel (Default: 5 gleichzeitig pro Modell)
python3 run_benchmark.py --concurrency 8

# Bestes Modell automatisch als DEFAULT_MODEL in const.py setzen
python3 run_benchmark.py --apply-default

# Threshold-Analyse + Export erneut ausführen, OHNE die API zu bemühen
# (nützlich nach Anpassungen an der Analyse-Logik):
python3 run_benchmark.py --from-results

# Beides kombiniert (aus existing results.json übernehmen):
python3 run_benchmark.py --from-results --apply-default
```

## Getestete Modelle

| Modell | Beschreibung |
|--------|-------------|
| `mistral-large-4` | Neuestes Flaggschiff (Preview), 1M Kontext |
| `mistral-large-latest` | Größtes Modell, beste Genauigkeit |
| `mistral-medium-latest` | Mittlere Größe, guter Kompromiss |
| `mistral-small-latest` | Kleinstes Modell, schnell & günstig |

## Testbilder (20 Bilder, lokal)

Bilder liegen lokal in `benchmark/images/` – **kein automatischer Download**.

| Kategorie | Anzahl | Dateien |
|-----------|--------|---------|
| Stringing | 6 | `stringing_1.jpg` … `stringing_6.jpg` |
| Spaghetti | 6 | `spaghetti_1.jpg` … `spaghetti_6.jpg` |
| Warping | 2 | `warping_1.webp`, `warping_2.jpg` |
| Layer Shift | 4 | `layer_shift_1.jpg` … `layer_shift_4.jpg` |
| Clean (Kontrolle) | 4 | `clean_1.jpg` … `clean_4.jpg` |

### Eigene Bilder hinzufügen

1. Bild nach `benchmark/images/` kopieren
2. In `run_benchmark.py` die `IMAGES`-Liste erweitern:

```python
{"file": "mein_bild.jpg", "category": "stringing",
 "expected": {"stringing_score_min": 40, "spaghetti_score_max": 30},
 "desc": "Beschreibung"},
```

## Auswertung

Das Skript gibt aus:

- **Accuracy**: Anteil der Bilder mit korrekten Scores (Ground Truth)
- **Composite Score**: Gewichtung 60% Accuracy + 25% Speed + 15% Cost
- **Avg Latenz**: Durchschnittliche Antwortzeit pro Bild (ohne Retry-Wartezeiten)
- **Kosten**: Geschätzt aus Mistral-Preisen (Token-basiert)
- **Detail-Tabelle**: Alle 4 Scores pro Bild und Modell
- **Empfehlung**: Bestes Modell nach Composite Score

### Parallelität & Rate-Limits

Die Bilder pro Modell werden parallel abgeschickt (`--concurrency`, Default 5).
Bei HTTP 429 respektiert der Benchmark den `Retry-After`-Header der Mistral-API
und wartet entsprechend; fehlt der Header, greift exponentielles Backoff
(0,5 s × 2ⁿ, max. 30 s). Auch 5xx-Fehler und Timeouts werden automatisch
wiederholt (`--max-retries`, Default 5). Permanente Fehler (z. B. 401, 400)
schlagen sofort fehl.

### Schwellenwerte pro Modell

Die Threshold-Analyse läuft **pro Modell**: Jedes Modell bekommt seine eigenen
Schwellenwerte, abgeleitet aus der eigenen Score-Verteilung (Kandidaten
konservativ/ausgewogen/aggressiv, gewählt nach bestem F1-Score; Minimum 10,
damit nie ein Alles-Alarm-Threshold entsteht). Dazu werden pro Modell
`min_confidence`, `smoothing_alpha` und `stringing_streak` empfohlen.

Mit `--apply-default` schreibt der Benchmark das beste Modell als
`DEFAULT_MODEL` **und** dessen Schwellenwerte als `DEFAULT_*`-Konstanten in
`custom_components/bambu_stringing/const.py` (auf die MIN/MAX-Grenzen
geklemmt). Ohne `--apply-default` landen die Schwellenwerte trotzdem in
`benchmark_data.json`:

- Top-Level `recommended_thresholds` — die Werte des empfohlenen Modells.
- `models[].recommended_thresholds` — die Werte je Modell.

Die Integration nutzt diese Werte als Fallback pro Modell: Der Options-Dialog
schlägt beim gewählten Modell dessen Benchmark-Werte vor (explizit gesetzte
Werte gewinnen immer), und der Benchmark-Sensor zeigt sie pro Modell an.

Mit `--from-results` wird die Threshold-Analyse und der Export in die
Integration aus dem vorhandenen `results.json` erneut ausgeführt — ohne
API-Aufrufe und ohne Kosten.

Ergebnisse werden als JSON in `results.json` gespeichert.

## Pre-Commit Workflow

```bash
# Vor jedem Commit Benchmark laufen lassen und Defaults aktualisieren
export MISTRAL_API_KEY=sk-...
python3 benchmark/run_benchmark.py --apply-default

# Oder ohne API-Kosten aus dem letzten Lauf:
python3 benchmark/run_benchmark.py --from-results --apply-default
```
