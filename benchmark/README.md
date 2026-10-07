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

# Bestes Modell automatisch als DEFAULT_MODEL in const.py setzen
python3 run_benchmark.py --apply-default
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
- **Avg Latenz**: Durchschnittliche Antwortzeit pro Bild
- **Kosten**: Geschätzt aus Mistral-Preisen (Token-basiert)
- **Detail-Tabelle**: Alle 4 Scores pro Bild und Modell
- **Empfehlung**: Bestes Modell nach Composite Score

Mit `--apply-default` wird das beste Modell automatisch als
`DEFAULT_MODEL` in `custom_components/bambu_stringing/const.py` gesetzt.

Ergebnisse werden als JSON in `results.json` gespeichert.

## Pre-Commit Workflow

```bash
# Vor jedem Commit Benchmark laufen lassen und Default aktualisieren
export MISTRAL_API_KEY=sk-...
python3 benchmark/run_benchmark.py --apply-default
```
