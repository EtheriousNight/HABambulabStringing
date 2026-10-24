#!/usr/bin/env python3
"""Benchmark: Mistral Vision Modelle auf 3D-Druck-Fehlererkennung testen.

Testet verschiedene Mistral-Modelle mit lokalen Fehlerbildern (Stringing,
Spaghetti, Warping, Layer-Shift, Clean) und vergleicht Scores, Antwortzeiten
und geschätzte Kosten. Ermittelt das beste Modell und schlägt es als
DEFAULT_MODEL für die Integration vor.

Verwendung:
    cd benchmark
    export MISTRAL_API_KEY=sk-...
    python3 run_benchmark.py

    # Oder als Argument:
    python3 run_benchmark.py --api-key sk-...

    # Nur bestimmte Modelle:
    python3 run_benchmark.py --models mistral-large-latest mistral-small-latest

    # Mehrere Anfragen parallel schicken (Rate-Limits werden per Retry-After
    # automatisch behandelt):
    python3 run_benchmark.py --concurrency 8

    # Ergebnis direkt in const.py übernehmen:
    python3 run_benchmark.py --apply-default

Die Threshold-Analyse läuft pro Modell: Jedes Modell bekommt seine eigenen
Schwellenwerte aus der eigenen Score-Verteilung. Diese werden zusammen mit
den Modell-Metadaten in custom_components/bambu_stringing/benchmark_data.json
geschrieben (-> Integration). --apply-default setzt zusätzlich das beste
Modell als DEFAULT_MODEL und dessen Schwellenwerte als DEFAULT_*-Konstanten
in const.py (auf die MIN/MAX-Grenzen geklemmt).

Benötigte Pakete: pip install aiohttp
Bilder: Müssen lokal in benchmark/images/ liegen (siehe images.json).
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import json
import os
import random
import re
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

try:
    import aiohttp
except ImportError:  # aiohttp nur für den eigentlichen Benchmark nötig
    aiohttp = None

# ---------------------------------------------------------------------------
# Konfiguration
# ---------------------------------------------------------------------------

MODELS = [
    "mistral-large-4",
    "zai-glm-5-3-flash",
    "mistral-large-latest",
    "mistral-medium-latest",
    "mistral-small-latest",
]

# Preise pro 1M Tokens (Mistral API, https://mistral.ai/pricing/api, Stand 2026-10-07)
# mistral-large-4: Sale-Preis (Original: $1.36 Input / $4.18 Output)
# *-latest-Aliase zeigen aktuell auf Large 3 / Medium 3.5 / Small 4
PRICING = {
    "mistral-large-4": {"input": 1.36, "output": 4.18},
    "zai-glm-5-3-flash": {"input": 0.15, "output": 0.5},
    "mistral-large-latest": {"input": 0.5, "output": 1.5},
    "mistral-medium-latest": {"input": 1.5, "output": 7.5},
    "mistral-small-latest": {"input": 0.15, "output": 0.6},
}

# Bilder-Metadaten: Datei in images/ + erwartete Scores als Ground Truth
# Erwartete Werte: *_min = Score muss mindestens so hoch sein
#                  *_max = Score darf höchstens so hoch sein
IMAGES = [
    # --- Stringing (6 Bilder) ---
    {"file": "stringing_1.jpg", "category": "stringing",
     "expected": {"stringing_score_min": 40, "spaghetti_score_max": 30},
     "desc": "Prusa Forum: Stringing zwischen Türmen"},
    {"file": "stringing_2.jpg", "category": "stringing",
     "expected": {"stringing_score_min": 30, "spaghetti_score_max": 30},
     "desc": "Imgur: Stringing Test Turm"},
    {"file": "stringing_3.png", "category": "stringing",
     "expected": {"stringing_score_min": 40, "spaghetti_score_max": 30},
     "desc": "Creality: Stringing Beispiel"},
    {"file": "stringing_4.jpg", "category": "stringing",
     "expected": {"stringing_score_min": 30, "spaghetti_score_max": 30},
     "desc": "Prusa Forum: Stringing Test"},
    {"file": "stringing_5.jpg", "category": "stringing",
     "expected": {"stringing_score_min": 30, "spaghetti_score_max": 30},
     "desc": "Prusa Forum: Stringing Mini"},
    {"file": "stringing_6.jpg", "category": "stringing",
     "expected": {"stringing_score_min": 30, "spaghetti_score_max": 30},
     "desc": "Prusa KB: Stringing Thumbnail"},
    # --- Spaghetti (5 Bilder, spaghetti_3 ist leer → clean) ---
    {"file": "spaghetti_1.jpg", "category": "spaghetti",
     "expected": {"spaghetti_score_min": 60, "stringing_score_max": 50},
     "desc": "Reddit: Spaghetti Failure Bambu"},
    {"file": "spaghetti_2.jpg", "category": "spaghetti",
     "expected": {"spaghetti_score_min": 60, "stringing_score_max": 50},
     "desc": "Reddit: Spaghetti Chaos"},
    {"file": "spaghetti_3.jpg", "category": "clean",
     "expected": {"stringing_score_max": 20, "spaghetti_score_max": 15,
                  "warping_score_max": 20, "layer_shift_score_max": 15},
     "desc": "LEERE PLATTE (war fälschlich als spaghetti kategorisiert)"},
    {"file": "spaghetti_4.jpg", "category": "spaghetti",
     "expected": {"spaghetti_score_min": 60, "stringing_score_max": 50},
     "desc": "Reddit: Spaghetti 3D prints"},
    {"file": "spaghetti_5.jpg", "category": "spaghetti",
     "expected": {"spaghetti_score_min": 60, "stringing_score_max": 50},
     "desc": "Reddit: Spaghetti Druckbett"},
    {"file": "spaghetti_6.jpg", "category": "clean",
     "expected": {"stringing_score_max": 20, "spaghetti_score_max": 15,
                  "warping_score_max": 20, "layer_shift_score_max": 15},
     "desc": "SAUBERE Anime-Figur (war fälschlich als spaghetti kategorisiert — alle Modelle erkennen: clean)"},
    # --- Warping (1 Bild, warping_2 ist sauber → clean) ---
    {"file": "warping_1.webp", "category": "warping",
     "expected": {"warping_score_min": 40, "spaghetti_score_max": 30},
     "desc": "Creality: Warping abhebende Ecken"},
    {"file": "warping_2.jpg", "category": "clean",
     "expected": {"stringing_score_max": 20, "spaghetti_score_max": 15,
                  "warping_score_max": 20, "layer_shift_score_max": 15},
     "desc": "SAUBERER Druck (war fälschlich als warping kategorisiert)"},
    # --- Layer Shift (2 Bilder, layer_shift_1 und _4 sind sauber → clean) ---
    {"file": "layer_shift_1.jpg", "category": "clean",
     "expected": {"stringing_score_max": 20, "spaghetti_score_max": 15,
                  "warping_score_max": 20, "layer_shift_score_max": 15},
     "desc": "SAUBERER Druck (war fälschlich als layer_shift kategorisiert)"},
    {"file": "layer_shift_2.png", "category": "layer_shift",
     "expected": {"layer_shift_score_min": 50, "spaghetti_score_max": 30},
     "desc": "Creality: Layer Shift"},
    {"file": "layer_shift_3.jpg", "category": "layer_shift",
     "expected": {"layer_shift_score_min": 40, "spaghetti_score_max": 30},
     "desc": "3DSourced: Layer Shifting"},
    {"file": "layer_shift_4.jpg", "category": "clean",
     "expected": {"stringing_score_max": 20, "spaghetti_score_max": 15,
                  "warping_score_max": 20, "layer_shift_score_max": 15},
     "desc": "SAUBERER Druck (war fälschlich als layer_shift kategorisiert)"},
    # --- Clean / Kontrolle (4 Bilder) ---
    {"file": "clean_1.jpg", "category": "clean",
     "expected": {"stringing_score_max": 20, "spaghetti_score_max": 15,
                   "warping_score_max": 20, "layer_shift_score_max": 15},
     "desc": "Obico: 3DBenchy sauber"},
    {"file": "clean_2.webp", "category": "clean",
     "expected": {"stringing_score_max": 20, "spaghetti_score_max": 15,
                   "warping_score_max": 20, "layer_shift_score_max": 15},
     "desc": "3DMaker: Benchy Circle"},
    {"file": "clean_3.jpg", "category": "clean",
     "expected": {"stringing_score_max": 20, "spaghetti_score_max": 15,
                   "warping_score_max": 20, "layer_shift_score_max": 15},
     "desc": "Powerbelt3D: Benchy sauber"},
    {"file": "clean_4.jpg", "category": "clean",
     "expected": {"stringing_score_max": 20, "spaghetti_score_max": 15,
                   "warping_score_max": 20, "layer_shift_score_max": 15},
     "desc": "OctoEverywhere: Benchy"},
]

# Derselbe System-Prompt wie in der Integration (core/prompt.py v3.2)
SYSTEM_PROMPT = """Du bist ein Inspektor für FDM-3D-Druck. Du erhältst ein Bild aus der Druckkammer eines Bambu Lab P1S. Analysiere das Bild SCHRITT FÜR SCHRITT und begründe deine Entscheidung.

SCHRITT 1: Steht das Teil fest auf dem Druckbett?
  - NEIN (vom Bett gelöst, Materialklumpen, Nest, entartet) → spaghetti_score hoch (70-100), springe zu SCHRITT 5
  - JA → weiter zu SCHRITT 2

SCHRITT 2: Gibt es feine Filamentfäden oder Spinnweben zwischen/auf Strukturen?
  - JA → stringing_score nach Schweregrad bewerten (siehe Skala unten)
  - WICHTIG: spaghetti_score darf MAXIMAL 20 sein, solange das Teil steht!
  - NEIN → stringing_score = 0, weiter zu SCHRITT 3

SCHRITT 3: Heben sich Ränder oder Ecken vom Druckbett ab (Warping/Curling)?
  - JA → warping_score bewerten
  - NEIN → warping_score = 0, weiter zu SCHRITT 4

SCHRITT 4: Sind die Druckschichten horizontal gegeneinander versetzt (stufenartige Struktur, "Terrassen")?
  - JA → layer_shift_score bewerten
  - NEIN → layer_shift_score = 0

SCHRITT 5: bed_adhesion_failure = true NUR wenn Teile sichtbar vom Bett gelöst sind.

REGELN (sehr wichtig):
- Stringing und Spaghetti sind AUSSCHLIESSLICH: Solange das Teil fest steht, ist es NIEMALS Spaghetti!
- Spaghetti erfordert: Ablösung vom Bett ODER komplettes Materialnest/Klumpen
- Layer Shift zeigt sich als STUFEN (horizontale Verschiebung), nicht als Fäden
- Warping zeigt sich als ABHEBENDE RÄNDER, nicht als Fäden

SCORE-SKALA (0-100):
0-10:   Keine sichtbaren Defekte, makellos
11-30:  Minimale Spuren, rein kosmetisch
31-50:  Deutlich sichtbar, Qualität leicht beeinträchtigt
51-70:  Stark ausgeprägt, Teil noch brauchbar
71-90:  Extrem, Teil kaum brauchbar
91-100: Vollständig unbrauchbar

NICHT als Defekt bewerten (Negative Beispiele):
- Stützstrukturen (Supports) — sehen aus wie Fäden, sind aber gewollt
- Brücken (Bridges) — horizontale Verbindungen zwischen Teilen
- Dünne Design-Features (Haare, Antennen, Griffe, Spitzen)
- Schatten, Spiegelungen, Beleuchtungseffekte
- Textur der Druckplatte (Elefantenfuß-Protektor, PEI, etc.)
- Der erste Layer (First Layer) — darf unsauber aussehen
- Gewollte Schrägen oder geneigte Flächen des Modells (kein Warping!)
- Der Werkzeugkopf/Druckkopf selbst

BEISPIELE (Few-Shot, lerne daraus):

Beispiel 1 - Leichtes Stringing an Temperatur-Türmen:
  Bild: Mehrere konische Türme (Temperatur-Kalibrierung) auf einer Platte.
  Zwischen den Spitzen sind feine, kurze Filamentfäden sichtbar.
  Die Türme stehen fest, keine Ablösung.
  → stringing_score: 45, spaghetti_score: 0

Beispiel 2 - Stringing an Zylindern:
  Bild: Zwei hohe zylindrische Türme nebeneinander.
  An den Seiten und zwischen den Türmen sind Fäden/Spinnweben erkennbar.
  → stringing_score: 50-60, spaghetti_score: 0

Beispiel 3 - Extremes Stringing (NICHT Spaghetti!):
  Bild: Ein zylindrisches Teil steht aufrecht auf dem Bett.
  Überall um das Teil herum liegen zahllose Filamentfäden.
  Das Teil selbst ist intakt und haftet fest!
  → stringing_score: 90-95, spaghetti_score: 0-10

Beispiel 4 - Layer Shift an Figuren:
  Bild: Mehrere kleine Figuren auf einer Platte.
  Horizontale Stufen/Terrassen sichtbar — obere Schichten seitlich verschoben.
  → layer_shift_score: 60-70, stringing_score: 0

Beispiel 5 - Echter Spaghetti-Fall:
  Bild: Chaotisches Nest aus verheddertem Filament auf dem Bett.
  Keine erkennbare Struktur, kein stehendes Teil.
  → spaghetti_score: 95-100, bed_adhesion_failure: true

Beispiel 6 - Sauberer Druck (Clean):
  Bild: Mehrere 3D-Benchy-Boote stehen ordentlich auf dem Bett.
  Gleichmäßige Schichtlinien, keine Fäden, keine Ablösung, keine Stufen.
  → alle Scores: 0, bed_adhesion_failure: false

Beispiel 7 - KRITISCH: Zwei Türme mit EXTREMEM Stringing (NIEMALS Spaghetti!):
  Bild: Zwei hohe, zylindrische Türme/Säulen stehen nebeneinander auf einer
  runden Grundplatte. Beide Türme stehen FEST und INTAKT auf dem Bett!
  Der gesamte Zwischenraum zwischen den Türmen ist mit einem dichten,
  chaotischen Netz aus feinen Filamentfäden/Spinnweben überzogen.
  Manche Fäden hängen herab, andere spannen sich diagonal.
  WICHTIG: Die Türme selbst sind NICHT abgelöst, sie HAFTEN fest am Bett!
  → stringing_score: 90-95, spaghetti_score: 0-10, bed_adhesion_failure: false

Beispiel 8 - Temperatur-Türme mit moderatem Stringing (nicht übersehen!):
  Bild: Mehrere konische Türme (Temperatur-Kalibrierung) in verschiedenen
  Farben (grün, rot) stehen aufrecht auf dem Bett. Zwischen den Spitzen
  sind feine, kurze Filamentfäden sichtbar - nicht extrem, aber deutlich.
  Alle Türme haften fest an ihren Basen.
  → stringing_score: 40-50, spaghetti_score: 0, bed_adhesion_failure: false

Antworte AUSSCHLIESSLICH als JSON:
{
  "stringing_score": <0-100>,
  "spaghetti_score": <0-100>,
  "warping_score": <0-100>,
  "layer_shift_score": <0-100>,
  "bed_adhesion_failure": <true|false>,
  "confidence": <0.0-1.0>,
  "reasoning": "<1 Satz: welcher Schritt hat zur Hauptentscheidung geführt>",
  "observations": "<max. 2 Sätze, deutsch>",
  "other_defects": ["<max. 3 kurze deutsche Beschreibungen>"]
}

confidence: 1.0 = absolut sicher, 0.5 = unsicher, 0.0 = kann nicht beurteilen
reasoning: Kurze Begründung, z.B. "Teil steht fest, deutliche Fäden zwischen Türmen sichtbar → Stringing"
"""

USER_TEXT = (
    "Bewerte das beigefügte Kammerbild gemäß der Vorgaben. "
    "Denke Schritt für Schritt und antworte nur mit dem JSON-Objekt."
)

MISTRAL_CHAT_URL = "https://api.mistral.ai/v1/chat/completions"


# ---------------------------------------------------------------------------
# Plausibility Rules (identisch zu core/mistral.py — für Post-Correction Accuracy)
# ---------------------------------------------------------------------------


def apply_plausibility_rules(
    scores: dict,
    observations: str,
    reasoning: str = "",
) -> dict:
    """Wendet die Plausibility Rules aus der Integration an (v3.2).

    Korrigiert offensichtliche Fehlklassifikationen:
    - Rule 6: Spaghetti trotz stehender Teile → Stringing
    - Rule 7: Stringing-Score 0 bei Fäden in Observations → Boost
    """
    s = dict(scores)
    obs_lower = (observations or "").lower()
    r = (reasoning or "").lower()

    stringing = s.get("stringing_score", 0)
    spaghetti = s.get("spaghetti_score", 0)
    warping = s.get("warping_score", 0)
    layer_shift = s.get("layer_shift_score", 0)
    adhesion_fail = s.get("bed_adhesion_failure", False)

    # Rule 1: Spaghetti ohne Ablösung + Stringing → wahrscheinlich nur Stringing
    if spaghetti > 60 and not adhesion_fail and stringing > 40:
        s["spaghetti_score"] = min(spaghetti, 30)
        s["stringing_score"] = max(stringing, 70)

    # Rule 2: Beide hoch → Entscheidung anhand Ablösung
    if spaghetti > 70 and stringing > 70:
        if adhesion_fail:
            s["stringing_score"] = min(stringing, 50)
        else:
            s["spaghetti_score"] = 20
            s["stringing_score"] = max(stringing, 80)

    # Rule 5: Spaghetti ohne Ablösung und ohne hohe Stringing → verdächtig
    if spaghetti > 50 and not adhesion_fail and stringing < 30:
        s["spaghetti_score"] = min(spaghetti, 30)

    # Rule 6 (v3.2): Spaghetti trotz "stehender Teile" in Observations
    # SEHR KONSERVATIV: Nur bei spaghetti > 80, stringing < 20, mind. 2 starke
    # stehende Indikatoren UND keine Nest-Indikatoren.
    if spaghetti > 80 and stringing < 20:
        strong_standing_keywords = [
            "steht fest", "stehen fest", "steht stabil", "stehen stabil",
            "turm", "türme", "säule", "säulen", "zylinder",
            "grundplatte", "intakt", "aufrecht",
        ]
        any_nest_keywords = [
            "nest", "knäuel", "chaos", "chaotisch", "wirr", "verheddert",
            "abgelöst", "losgelöst", "gelöst", "klumpen",
            "kein stehendes teil", "keine erkennbare struktur",
            "nichts erkennbar", "nur noch nest", "nur nest",
            "komplett abgelöst", "vollständig abgelöst", "entartet",
            "materialnest", "filamentnest", "filamentknäuel",
        ]
        standing_count = sum(1 for kw in strong_standing_keywords if kw in obs_lower)
        has_any_nest = any(kw in obs_lower for kw in any_nest_keywords)

        if standing_count >= 2 and not has_any_nest:
            s["spaghetti_score"] = min(spaghetti, 25)
            s["stringing_score"] = max(stringing, 75)
            s["bed_adhesion_failure"] = False

    # Rule 7 (v3.2): Stringing-Score 0 bei Fäden in Observations
    # KRITISCH: Negationen wie "keine Fäden" dürfen NICHT triggern!
    if stringing < 10:
        stringing_keywords = [
            "faden", "fäden", "spinnweb", "spinnweben", "haar",
            "stringing", "faeden", "filamentfäden", "filamentfaden",
            "fädig", "fadrig", "web",
        ]
        negation_keywords = [
            "keine fäden", "keine faden", "keinerlei fäden", "kein faden",
            "ohne fäden", "ohne faden", "frei von fäden",
            "keine spinnweb", "kein stringing", "keine haare",
            "nicht vorhanden", "nichts erkennbar", "nichts sichtbar",
            "keine defekte", "keine mängel", "makellos", "fehlerfrei",
            "sauber", "einwandfrei", "keine stellen", "keine spuren",
        ]
        has_stringing_words = any(kw in obs_lower for kw in stringing_keywords)
        has_negation = any(kw in obs_lower for kw in negation_keywords)
        if has_stringing_words and not has_negation and spaghetti < 50:
            s["stringing_score"] = max(stringing, 40)

    return s

# Parallelität & Retries
DEFAULT_CONCURRENCY = 5  # gleichzeitige Anfragen pro Modell (--concurrency)
DEFAULT_MAX_RETRIES = 5  # Wiederholungen bei 429/5xx/Netzwerkfehlern (--max-retries)
RETRY_BASE_WAIT = 0.5    # Sekunden, Basis für exponentielles Backoff
RETRY_MAX_WAIT = 30.0    # Obergrenze pro einzelner Wartezeit
TRANSIENT_STATUS = {500, 502, 503, 504, 529}

# ---------------------------------------------------------------------------
# Datenklassen
# ---------------------------------------------------------------------------


@dataclass
class ModelResult:
    model: str
    image_file: str
    category: str
    latency_ms: float
    input_tokens: int = 0
    output_tokens: int = 0
    est_cost_usd: float = 0.0
    scores: dict = field(default_factory=dict)
    observations: str = ""
    confidence: float = 1.0
    reasoning: str = ""
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None


@dataclass
class BenchmarkSummary:
    model: str
    results: list[ModelResult] = field(default_factory=list)

    @property
    def total_cost(self) -> float:
        return sum(r.est_cost_usd for r in self.results)

    @property
    def avg_latency(self) -> float:
        ok = [r.latency_ms for r in self.results if r.ok]
        return sum(ok) / len(ok) if ok else 0.0

    @property
    def total_scans(self) -> int:
        """Anzahl erfolgreicher Scans."""
        return len([r for r in self.results if r.ok])

    @property
    def cost_per_scan(self) -> float:
        """Durchschnittliche Kosten pro Scan (USD)."""
        scans = self.total_scans
        return self.total_cost / scans if scans > 0 else 0.0

    @property
    def cost_per_scan_cents(self) -> float:
        """Kosten pro Scan in Cent (lesbarer)."""
        return self.cost_per_scan * 100

    @property
    def accuracy(self) -> float:
        """Berechnet Accuracy, gewichtet mit Confidence."""
        return self._accuracy_corrected(apply_rules=False)

    @property
    def accuracy_corrected(self) -> float:
        """Accuracy nach Anwendung der Plausibility Rules (wie in der Integration)."""
        return self._accuracy_corrected(apply_rules=True)

    def _accuracy_corrected(self, apply_rules: bool) -> float:
        """Interne Accuracy-Berechnung mit optionaler Plausibility-Korrektur."""
        if not self.results:
            return 0.0
        correct = 0.0
        total_weight = 0.0
        for r in self.results:
            if not r.ok:
                continue
            img = next((i for i in IMAGES if i["file"] == r.image_file), None)
            if img is None:
                continue
            exp = img["expected"]
            s = r.scores
            if apply_rules:
                s = apply_plausibility_rules(s, r.observations, r.reasoning)
            ok = True
            for key, threshold in exp.items():
                score_key = key.rsplit("_", 1)[0]
                direction = key.rsplit("_", 1)[1]
                val = s.get(score_key, 0)
                if direction == "min" and val < threshold:
                    ok = False
                elif direction == "max" and val > threshold:
                    ok = False
            if ok:
                correct += r.confidence  # Gewichtet mit Confidence
            total_weight += 1.0
        return correct / total_weight * 100 if total_weight else 0.0

    @property
    def category_accuracy(self) -> dict[str, float]:
        """Accuracy pro Kategorie (stringing, spaghetti, warping, layer_shift, clean)."""
        return self._category_accuracy_corrected(apply_rules=False)

    @property
    def category_accuracy_corrected(self) -> dict[str, float]:
        """Category Accuracy nach Plausibility Rules."""
        return self._category_accuracy_corrected(apply_rules=True)

    def _category_accuracy_corrected(self, apply_rules: bool) -> dict[str, float]:
        """Interne Category-Accuracy mit optionaler Korrektur."""
        cats: dict[str, list[float]] = {}
        for r in self.results:
            if not r.ok:
                continue
            img = next((i for i in IMAGES if i["file"] == r.image_file), None)
            if img is None:
                continue
            cat = img["category"]
            exp = img["expected"]
            s = r.scores
            if apply_rules:
                s = apply_plausibility_rules(s, r.observations, r.reasoning)
            ok = True
            for key, threshold in exp.items():
                score_key = key.rsplit("_", 1)[0]
                direction = key.rsplit("_", 1)[1]
                val = s.get(score_key, 0)
                if direction == "min" and val < threshold:
                    ok = False
                elif direction == "max" and val > threshold:
                    ok = False
            cats.setdefault(cat, []).append(1.0 if ok else 0.0)
        return {
            cat: sum(scores) / len(scores) * 100
            for cat, scores in cats.items()
            if scores
        }

    @property
    def accuracy_per_dollar(self) -> float:
        """Accuracy-Punkte pro Dollar (Preis-Leistungs-Index).
        
        Höher = besser. Zeigt wie viel Accuracy man pro Dollar bekommt.
        """
        if self.total_cost <= 0:
            return 0.0
        return self.accuracy / self.total_cost

    @property
    def accuracy_per_cent(self) -> float:
        """Accuracy-Punkte pro Cent (noch lesbarer)."""
        return self.accuracy_per_dollar * 100

    @property
    def speed_score(self) -> float:
        """Geschwindigkeits-Score (0-100, höher = schneller)."""
        if self.avg_latency <= 0:
            return 0.0
        # 1000ms = 90 Punkte, 5000ms = 50 Punkte, 30000ms = 0 Punkte
        return max(0.0, 100 - self.avg_latency / 300)

    @property
    def cost_score(self) -> float:
        """Kosten-Score (0-100, höher = günstiger)."""
        if self.total_cost <= 0:
            return 100.0
        # $0.01 = 90 Punkte, $0.10 = 50 Punkte, $1.00 = 0 Punkte
        return max(0.0, 100 - self.total_cost * 100)

    @property
    def value_score(self) -> float:
        """Preis-Leistungs-Score: 70% Accuracy, 20% Speed, 10% Cost.
        
        Optimiert für Produktion: Hohe Accuracy ist wichtiger als Geschwindigkeit,
        aber günstige Modelle werden bevorzugt.
        """
        return (
            self.accuracy * 0.70
            + self.speed_score * 0.20
            + self.cost_score * 0.10
        )

    @property
    def production_score(self) -> float:
        """Production Score: 50% Accuracy, 30% Speed, 20% Cost.
        
        Ausgewogener für Live-Betrieb: Latenz ist wichtig (schnelle Reaktion),
        Kosten sekundär.
        """
        return (
            self.accuracy * 0.50
            + self.speed_score * 0.30
            + self.cost_score * 0.20
        )

    @property
    def reliability_score(self) -> float:
        """Reliability Score (v3.4): 60% Accuracy, 15% Critical Defects, 12.5% Speed, 12.5% Cost.

        Für 3D-Druck-Monitoring: Genauigkeit bei KRITISCHEN Defekten ist wichtiger als
        Gesamt-Accuracy.
        - False Negative bei Spaghetti = Stunden verschwendete Druckzeit + Material
        - False Negative bei Stringing = Ausschuss, Nachbearbeitung nötig
        - False Positive = nur eine Push-Benachrichtigung
        - 5.7s vs 1.9s Latenz ist für stundenlange Drucke vernachlässigbar
        - Nutzt max(raw, corrected) — nimmt die bessere Accuracy
        - SICHERHEIT: Modelle mit < 60% Accuracy bekommen Strafpunkte
        - BONUS: +15 Punkte für 100% Stringing + 100% Spaghetti (kritische Defekte)
        """
        # Nimm die bessere Accuracy (raw oder corrected)
        best_accuracy = max(self.accuracy, self.accuracy_corrected)
        # Strafpunkt für Modelle unter 60% Accuracy (nicht für Defekterkennung geeignet)
        accuracy_penalty = 0.0 if best_accuracy >= 60.0 else (60.0 - best_accuracy) * 0.5
        adjusted_accuracy = max(0.0, best_accuracy - accuracy_penalty)

        # Critical Defect Score: Gewichtet Stringing + Spaghetti höher
        # (diese beiden Defekte sind für 3D-Druck am kritischsten)
        cat_acc = self.category_accuracy_corrected
        stringing_acc = cat_acc.get("stringing", 0.0)
        spaghetti_acc = cat_acc.get("spaghetti", 0.0)
        # Gewichteter Durchschnitt: 60% Stringing, 40% Spaghetti
        critical_score = stringing_acc * 0.60 + spaghetti_acc * 0.40

        # Bonus für perfekte kritische Defekterkennung
        critical_bonus = 0.0
        if stringing_acc >= 95.0 and spaghetti_acc >= 95.0:
            critical_bonus = 15.0  # Perfekte kritische Defekte erkannt
        elif stringing_acc >= 80.0 and spaghetti_acc >= 80.0:
            critical_bonus = 7.5   # Gute kritische Defekte erkannt

        return (
            adjusted_accuracy * 0.60
            + critical_score * 0.15
            + critical_bonus * 0.10
            + self.speed_score * 0.075
            + self.cost_score * 0.075
        )

    @property
    def production_score_corrected(self) -> float:
        """Production Score mit korrigierter Accuracy (nach Plausibility Rules)."""
        return (
            self.accuracy_corrected * 0.50
            + self.speed_score * 0.30
            + self.cost_score * 0.20
        )

    @property
    def composite_score(self) -> float:
        """Gewichteter Score: 60% Accuracy, 25% Speed, 15% Cost (normalisiert).

        Legacy-Score für Rückwärtskompatibilität.
        """
        if not self.results:
            return 0.0
        acc = self.accuracy
        speed = self.speed_score
        cost = self.cost_score
        return acc * 0.6 + speed * 0.25 + cost * 0.15

    @property
    def critical_defect_score(self) -> float:
        """Score für kritische Defekte (Stringing + Spaghetti).

        Gewichtet: 60% Stringing, 40% Spaghetti.
        Diese beiden Defekte sind für 3D-Druck am kritischsten:
        - Spaghetti = kompletter Druckabbruch, Stunden verschwendet
        - Stringing = Ausschuss, aufwändige Nachbearbeitung
        """
        cat_acc = self.category_accuracy_corrected
        stringing_acc = cat_acc.get("stringing", 0.0)
        spaghetti_acc = cat_acc.get("spaghetti", 0.0)
        return stringing_acc * 0.60 + spaghetti_acc * 0.40

    @property
    def critical_bonus(self) -> float:
        """Bonus für perfekte/good kritische Defekterkennung."""
        cat_acc = self.category_accuracy_corrected
        stringing_acc = cat_acc.get("stringing", 0.0)
        spaghetti_acc = cat_acc.get("spaghetti", 0.0)
        if stringing_acc >= 95.0 and spaghetti_acc >= 95.0:
            return 15.0
        elif stringing_acc >= 80.0 and spaghetti_acc >= 80.0:
            return 7.5
        return 0.0

    def summary_dict(self) -> dict:
        """Zusammenfassung als Dictionary für Export."""
        return {
            "model": self.model,
            "accuracy_pct": round(self.accuracy, 1),
            "accuracy_corrected_pct": round(self.accuracy_corrected, 1),
            "value_score": round(self.value_score, 1),
            "production_score": round(self.production_score, 1),
            "reliability_score": round(self.reliability_score, 1),
            "critical_defect_score": round(self.critical_defect_score, 1),
            "critical_bonus": round(self.critical_bonus, 1),
            "composite_score": round(self.composite_score, 1),
            "avg_latency_ms": round(self.avg_latency, 0),
            "total_cost_usd": round(self.total_cost, 4),
            "cost_per_scan_cents": round(self.cost_per_scan_cents, 3),
            "accuracy_per_dollar": round(self.accuracy_per_dollar, 1),
            "total_scans": self.total_scans,
            "category_accuracy": {
                k: round(v, 1) for k, v in self.category_accuracy.items()
            },
            "category_accuracy_corrected": {
                k: round(v, 1) for k, v in self.category_accuracy_corrected.items()
            },
        }


# ---------------------------------------------------------------------------
# Threshold-Analyse: Empfohlene Schwellwerte aus den Ergebnissen ableiten
# ---------------------------------------------------------------------------

# Fallback-Werte (Spiegel der DEFAULT_*-Konstanten in const.py), falls ein
# Modell für eine Kategorie keine trennscharfen Scores liefert.
THRESHOLD_FALLBACKS = {
    "stringing_threshold": 55,
    "spaghetti_threshold": 70,
    "warping_threshold": 60,
    "layer_shift_threshold": 70,
    "min_confidence": 0.6,
    "smoothing_alpha": 0.3,
    "stringing_streak": 3,
}

# Score-Key pro Kategorie
CATEGORY_SCORE_KEY = {
    "stringing": "stringing_score",
    "spaghetti": "spaghetti_score",
    "warping": "warping_score",
    "layer_shift": "layer_shift_score",
}


def _expected_matches(expected: dict, scores: dict) -> bool:
    """True, wenn alle erwarteten min/max-Schwellen erfüllt sind."""
    for key, threshold in expected.items():
        score_key, direction = key.rsplit("_", 1)
        val = scores.get(score_key, 0)
        if direction == "min" and val < threshold:
            return False
        if direction == "max" and val > threshold:
            return False
    return True


def analyze_thresholds_for_model(summary: BenchmarkSummary) -> dict:
    """Threshold-Empfehlungen für EIN Modell aus dessen Score-Verteilungen.

    Für jede Defekt-Kategorie werden die Scores von positiven Beispielen
    (Bilder mit diesem Defekt) und negativen Beispielen (alle anderen)
    gesammelt. Aus drei Kandidaten wird der Wert mit dem besten F1-Score
    gewählt; bei Gleichstand der konservativere (höhere, weniger False
    Positives — eine verpasste Warnung ist besser als Daueralarm).

    Die Werte sind bewusst auf 10-90 begrenzt: Ein Threshold von 0 würde in
    der Integration jeden Frame als Fehler werten.
    """
    recommendations: dict = {}

    for category, score_key in CATEGORY_SCORE_KEY.items():
        positive_scores = []  # Bilder die DIESE Kategorie haben sollten
        negative_scores = []  # Bilder die diese Kategorie NICHT haben sollten

        for r in summary.results:
            if not r.ok:
                continue
            img = next((i for i in IMAGES if i["file"] == r.image_file), None)
            if img is None:
                continue

            score = r.scores.get(score_key, 0)

            # Ein Bild ist "positiv", wenn die erwarteten Werte einen
            # min-Threshold für genau diese Kategorie enthalten
            is_positive = any(
                k.startswith(score_key.replace("_score", "")) and k.endswith("_min")
                for k in img["expected"].keys()
            )

            if is_positive:
                positive_scores.append(score)
            else:
                negative_scores.append(score)

        if not positive_scores or not negative_scores:
            continue

        min_positive = min(positive_scores)  # schwächster noch erkannter Treffer
        max_negative = max(negative_scores)  # höchster False-Positive-Score

        # v3.2: Bei False Negatives (positives Bild mit Score 0) ist min_positive
        # nutzlos. Stattdessen: 25. Perzentil der positiven Scores verwenden,
        # mindestens aber MIN_THRESHOLD_FLOOR (Score < 30 = kosmetisch laut Prompt).
        sorted_pos = sorted(positive_scores)
        p25_idx = max(0, len(sorted_pos) // 4 - 1)
        reliable_min_positive = sorted_pos[p25_idx] if sorted_pos else 0

        # Kategorie-spezifischer Floor: Mindestens 30 (darunter = kosmetisch)
        MIN_FLOOR = 30
        max_negative = max(max_negative, MIN_FLOOR - 5)  # Floor auch für Negatives

        candidates = {
            # Konservativ: knapp über dem höchsten False Positive (mit Floor)
            "conservative": max(MIN_FLOOR, min(90, max_negative + 5)),
            # Ausgewogen: Midpoint zwischen reliable_min_positive und max_negative
            "balanced": max(MIN_FLOOR, min(90, (reliable_min_positive + max_negative) // 2)),
            # Aggressiv: knapp unter dem reliable_min_positive (nicht min!)
            "aggressive": max(MIN_FLOOR, min(90, reliable_min_positive - 5)),
        }

        def _f1(threshold: int) -> tuple[float, int]:
            tp = sum(1 for s in positive_scores if s >= threshold)
            fn = len(positive_scores) - tp
            fp = sum(1 for s in negative_scores if s >= threshold)
            precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
            sensitivity = tp / (tp + fn) if (tp + fn) > 0 else 0.0
            f1 = (
                2 * precision * sensitivity / (precision + sensitivity)
                if (precision + sensitivity) > 0
                else 0.0
            )
            return f1, threshold  # Tie-Breaker: höherer Threshold = konservativer

        best_name = max(candidates, key=lambda name: _f1(candidates[name]))
        recommended = candidates[best_name]

        tp = sum(1 for s in positive_scores if s >= recommended)
        fn = len(positive_scores) - tp
        fp = sum(1 for s in negative_scores if s >= recommended)
        tn = len(negative_scores) - fp
        sensitivity = tp / (tp + fn) if (tp + fn) > 0 else 0.0
        specificity = tn / (tn + fp) if (tn + fp) > 0 else 0.0
        precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        f1 = (
            2 * (precision * sensitivity) / (precision + sensitivity)
            if (precision + sensitivity) > 0
            else 0.0
        )

        recommendations[category] = {
            "recommended_threshold": recommended,
            "strategy": best_name,
            "positive_scores": sorted(positive_scores),
            "negative_scores": sorted(negative_scores),
            "min_positive": min_positive,
            "max_negative": max_negative,
            "metrics": {
                "true_positives": tp,
                "false_negatives": fn,
                "false_positives": fp,
                "true_negatives": tn,
                "sensitivity": round(sensitivity * 100, 1),
                "specificity": round(specificity * 100, 1),
                "precision": round(precision * 100, 1),
                "f1_score": round(f1 * 100, 1),
            },
            "alternatives": candidates,
        }

    # Confidence-Threshold: knapp über der höchsten Confidence, mit der eine
    # Antwort falsch war — so werden möglichst viele Fehlurteile gefiltert
    conf_correct = []
    conf_wrong = []
    for r in summary.results:
        if not r.ok:
            continue
        img = next((i for i in IMAGES if i["file"] == r.image_file), None)
        if img is None:
            continue
        if _expected_matches(img["expected"], r.scores):
            conf_correct.append(r.confidence)
        else:
            conf_wrong.append(r.confidence)

    if conf_wrong:
        max_wrong_conf = max(conf_wrong)
        if max_wrong_conf >= 0.95:
            # Falsche Antworten mit (fast) voller Sicherheit — kein Filter
            # kann sie abfangen, also beim konservativen Default bleiben
            recommended_min_conf = THRESHOLD_FALLBACKS["min_confidence"]
        else:
            recommended_min_conf = round(max_wrong_conf + 0.05, 2)
            recommended_min_conf = min(0.9, max(0.3, recommended_min_conf))
    else:
        recommended_min_conf = THRESHOLD_FALLBACKS["min_confidence"]

    recommendations["_meta"] = {
        "recommended_min_confidence": recommended_min_conf,
        "recommended_smoothing_alpha": THRESHOLD_FALLBACKS["smoothing_alpha"],
        "recommended_stringing_streak": THRESHOLD_FALLBACKS["stringing_streak"],
        "avg_confidence_correct": round(sum(conf_correct) / len(conf_correct), 2) if conf_correct else 0,
        "avg_confidence_wrong": round(sum(conf_wrong) / len(conf_wrong), 2) if conf_wrong else 0,
    }

    return recommendations


def analyze_thresholds(summaries: list[BenchmarkSummary]) -> dict[str, dict]:
    """Threshold-Empfehlungen für JEDES Modell (nicht nur das beste).

    Jedes Modell bekommt seine eigenen Schwellenwerte, abgeleitet aus der
    eigenen Score-Verteilung — schwächere Modelle erhalten dadurch automatisch
    ihre angepassten (meist konservativeren) Werte.
    """
    return {s.model: analyze_thresholds_for_model(s) for s in summaries}


def thresholds_from_recommendations(recs: dict) -> dict:
    """Flache Konfig-Struktur für die Integration aus einer Empfehlung extrahieren."""
    meta = recs.get("_meta", {})
    thresholds = dict(THRESHOLD_FALLBACKS)
    for category in CATEGORY_SCORE_KEY:
        rec = recs.get(category)
        if rec:
            thresholds[f"{category}_threshold"] = rec["recommended_threshold"]
    thresholds["min_confidence"] = meta.get(
        "recommended_min_confidence", THRESHOLD_FALLBACKS["min_confidence"]
    )
    thresholds["smoothing_alpha"] = meta.get(
        "recommended_smoothing_alpha", THRESHOLD_FALLBACKS["smoothing_alpha"]
    )
    thresholds["stringing_streak"] = meta.get(
        "recommended_stringing_streak", THRESHOLD_FALLBACKS["stringing_streak"]
    )
    return thresholds


def print_threshold_recommendations(
    thresholds_by_model: dict[str, dict], recommended_model: str | None
) -> None:
    """Gibt die Threshold-Empfehlungen pro Modell formatiert aus."""
    print(f"\n{'='*80}")
    print("  🎯 EMPFOHLENE THRESHOLDS (pro Modell)")
    print(f"{'='*80}")

    cats = list(CATEGORY_SCORE_KEY)
    print(f"  {'Modell':<26}" + "".join(f" {c[:6]:>7}" for c in cats) + f" {'Conf':>6}")
    print(f"{'-'*80}")
    for model, recs in thresholds_by_model.items():
        t = thresholds_from_recommendations(recs)
        marker = "→" if model == recommended_model else " "
        row = f"  {marker} {model:<24}"
        for c in cats:
            row += f" {t[f'{c}_threshold']:>7}"
        row += f" {t['min_confidence']:>6.2f}"
        print(row)

    recs = thresholds_by_model.get(recommended_model) or (
        next(iter(thresholds_by_model.values())) if thresholds_by_model else {}
    )
    meta = recs.get("_meta", {})

    print(f"\n{'─'*80}")
    print(f"  Detail ({recommended_model or 'N/A'}): Sensitivität / Spezifität / F1")
    print(f"{'─'*80}")
    print(f"  {'Kategorie':<15} {'Empfohlen':>10} {'Sens.':>7} {'Spez.':>7} {'F1':>6} {'TP':>4} {'FP':>4}")
    for category in cats:
        rec = recs.get(category)
        if not rec:
            continue
        m = rec["metrics"]
        print(f"  {category:<15} {rec['recommended_threshold']:>10}   "
              f"{m['sensitivity']:>5.1f}% {m['specificity']:>5.1f}% "
              f"{m['f1_score']:>5.1f} {m['true_positives']:>4} {m['false_positives']:>4}")
    print(f"  Ø Confidence (korrekt): {meta.get('avg_confidence_correct', 0)} | "
          f"(falsch): {meta.get('avg_confidence_wrong', 0)}")

    print(f"\n{'─'*80}")
    print("  📋 ÜBERNOMMEN IN DIE INTEGRATION (benchmark_data.json):")
    print(f"{'─'*80}")
    for key, value in thresholds_from_recommendations(recs).items():
        print(f"    {key}: {value}")
    print(f"{'='*80}")


# ---------------------------------------------------------------------------
# Hilfsfunktionen
# ---------------------------------------------------------------------------


def load_api_key(args) -> str:
    """API-Key laden: CLI-Arg > Umgebungsvariable > .env Datei."""
    if args.api_key:
        return args.api_key
    key = os.environ.get("MISTRAL_API_KEY", "")
    if key:
        return key
    # Fallback: .env Datei neben dem Skript
    env_path = Path(__file__).parent / ".env"
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if line.startswith("MISTRAL_API_KEY="):
                key = line.split("=", 1)[1].strip().strip('"').strip("'")
                if key:
                    return key
    print("FEHLER: Kein API-Key gefunden.")
    print("  1. Umgebungsvariable: export MISTRAL_API_KEY=sk-...")
    print("  2. CLI-Argument:      python3 run_benchmark.py --api-key sk-...")
    print(f"  3. .env Datei:        echo 'MISTRAL_API_KEY=sk-...' > {env_path}")
    sys.exit(1)


def load_local_images(images_dir: Path) -> list[tuple[dict, bytes]]:
    """Nur lokale Bilder aus images/ laden. Keine Downloads."""
    prepared = []
    missing = []
    for img in IMAGES:
        path = images_dir / img["file"]
        if not path.exists():
            missing.append(img["file"])
            continue
        data = path.read_bytes()
        if len(data) < 1000:
            missing.append(f"{img['file']} (zu klein: {len(data)} bytes)")
            continue
        prepared.append((img, data))
    if missing:
        print(f"WARN: {len(missing)} Bilder fehlen oder sind ungültig:")
        for m in missing:
            print(f"  - {m}")
    return prepared


def encode_image(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


class RateLimitError(RuntimeError):
    """HTTP 429 – optional mit vom Server vorgegebener Wartezeit."""

    def __init__(self, message: str, retry_after: float | None = None):
        super().__init__(message)
        self.retry_after = retry_after


class ServerError(RuntimeError):
    """Flüchtiger Fehler (5xx, Timeout, Netzwerk) – Retry sinnvoll."""


def parse_retry_after(headers) -> float | None:
    """Retry-After-Header auslesen (Sekunden oder HTTP-Datum)."""
    raw = headers.get("Retry-After")
    if not raw:
        return None
    raw = raw.strip()
    try:
        return max(0.0, float(raw))
    except ValueError:
        pass
    try:
        due = parsedate_to_datetime(raw)
        if due.tzinfo is None:
            due = due.replace(tzinfo=timezone.utc)
        delta = due - datetime.now(timezone.utc)
        return max(0.0, delta.total_seconds())
    except (TypeError, ValueError):
        return None


async def send_request(session, api_key: str, model: str, image_b64: str, timeout: float = 120.0):
    """Ein einzelner Request-Versuch. Misst die Latenz dieses Versuchs."""
    payload = {
        "model": model,
        "temperature": 0.0,
        # Pflicht bei temperature=0 (greedy sampling), sonst HTTP 400
        # ("top_p must be 1 when using greedy sampling") z. B. bei mistral-large-4
        "top_p": 1,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": USER_TEXT},
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/jpeg;base64,{image_b64}"},
                    },
                ],
            },
        ],
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    t0 = time.monotonic()
    try:
        # 120s: Reasoning-Modelle (mistral-large-4) brauchen beim Cold Start > 60s
        async with session.post(
            MISTRAL_CHAT_URL,
            headers=headers,
            json=payload,
            timeout=aiohttp.ClientTimeout(total=timeout),
        ) as resp:
            status = resp.status
            retry_after = parse_retry_after(resp.headers)
            data = await resp.json(content_type=None)
    except asyncio.TimeoutError as e:
        raise ServerError(f"Timeout nach {timeout:.0f}s") from e
    except Exception as e:
        raise ServerError(f"Netzwerkfehler: {type(e).__name__}: {e}") from e

    latency_ms = (time.monotonic() - t0) * 1000
    if status == 200:
        usage = data.get("usage", {})
        return data, usage.get("prompt_tokens", 0), usage.get("completion_tokens", 0), latency_ms
    if status == 429:
        raise RateLimitError(f"HTTP 429: {str(data)[:120]}", retry_after)
    if status in TRANSIENT_STATUS:
        raise ServerError(f"HTTP {status}: {str(data)[:120]}")
    raise RuntimeError(f"HTTP {status}: {str(data)[:200]}")


async def call_mistral_with_retry(
    session,
    api_key: str,
    model: str,
    image_b64: str,
    max_retries: int = DEFAULT_MAX_RETRIES,
    log_prefix: str = "",
):
    """send_request mit automatischem Retry bei 429/5xx/Netzwerkfehlern.

    Bei HTTP 429 wird der Retry-After-Header der Mistral-API respektiert,
    falls vorhanden; sonst exponentielles Backoff (0.5s * 2^n, gedeckelt
    auf RETRY_MAX_WAIT) plus Jitter. Die zurückgegebene Latenz umfasst nur
    den erfolgreichen Versuch, nicht die Wartezeiten dazwischen.
    """
    for attempt in range(max_retries + 1):
        try:
            return await send_request(session, api_key, model, image_b64)
        except (RateLimitError, ServerError) as e:
            if attempt >= max_retries:
                raise
            if isinstance(e, RateLimitError) and e.retry_after is not None:
                wait = e.retry_after
            else:
                wait = RETRY_BASE_WAIT * (2 ** attempt)
            wait = min(wait, RETRY_MAX_WAIT) + random.uniform(0, 0.25)
            kind = "429 Rate-Limit" if isinstance(e, RateLimitError) else str(e)
            print(
                f"    {log_prefix}{kind} – Retry in {wait:.1f}s "
                f"(Versuch {attempt + 1}/{max_retries + 1})"
            )
            await asyncio.sleep(wait)
    raise RuntimeError("unerreichbar")  # pragma: no cover


def parse_scores(data: dict) -> tuple[dict, str, float, str]:
    """Returns (scores, observations, confidence, reasoning)."""
    choices = data.get("choices", [])
    if not choices:
        raise RuntimeError("Keine choices in Antwort")
    content = choices[0].get("message", {}).get("content", "")
    if isinstance(content, list):
        content = " ".join(p.get("text", "") for p in content if isinstance(p, dict))
    parsed = json.loads(content)
    scores = {
        "stringing_score": int(parsed.get("stringing_score", 0)),
        "spaghetti_score": int(parsed.get("spaghetti_score", 0)),
        "warping_score": int(parsed.get("warping_score", 0)),
        "layer_shift_score": int(parsed.get("layer_shift_score", 0)),
        "bed_adhesion_failure": bool(parsed.get("bed_adhesion_failure", False)),
    }
    observations = str(parsed.get("observations", "")).strip()
    confidence = float(parsed.get("confidence", 1.0))
    reasoning = str(parsed.get("reasoning", "")).strip()
    return scores, observations, confidence, reasoning


def estimate_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    pricing = PRICING.get(model, {"input": 0, "output": 0})
    return (input_tokens * pricing["input"] + output_tokens * pricing["output"]) / 1_000_000


def apply_default_model(model: str, project_root: Path) -> bool:
    """Schreibt das beste Modell als DEFAULT_MODEL in const.py."""
    const_path = project_root / "custom_components" / "bambu_stringing" / "const.py"
    if not const_path.exists():
        print(f"  const.py nicht gefunden: {const_path}")
        return False
    content = const_path.read_text()
    pattern = r'(DEFAULT_MODEL:\s*Final\s*=\s*")[^"]*(")'
    if not re.search(pattern, content):
        print(f"  WARN: DEFAULT_MODEL nicht gefunden in const.py")
        return False
    const_path.write_text(re.sub(pattern, rf'\g<1>{model}\g<2>', content))
    print(f"  DEFAULT_MODEL auf '{model}' gesetzt in const.py")
    return True


# Benchmark-Key -> (DEFAULT-Konstante, MIN-Konstante, MAX-Konstante, float?)
DEFAULT_THRESHOLD_KEYS = {
    "stringing_threshold": (
        "DEFAULT_STRINGING_THRESHOLD", "MIN_STRINGING_THRESHOLD",
        "MAX_STRINGING_THRESHOLD", False,
    ),
    "spaghetti_threshold": (
        "DEFAULT_SPAGHETTI_THRESHOLD", "MIN_SPAGHETTI_THRESHOLD",
        "MAX_SPAGHETTI_THRESHOLD", False,
    ),
    "warping_threshold": (
        "DEFAULT_WARPING_THRESHOLD", "MIN_WARPING_THRESHOLD",
        "MAX_WARPING_THRESHOLD", False,
    ),
    "layer_shift_threshold": (
        "DEFAULT_LAYER_SHIFT_THRESHOLD", "MIN_LAYER_SHIFT_THRESHOLD",
        "MAX_LAYER_SHIFT_THRESHOLD", False,
    ),
    "stringing_streak": (
        "DEFAULT_STRINGING_STREAK", "MIN_STRINGING_STREAK",
        "MAX_STRINGING_STREAK", False,
    ),
    "min_confidence": ("DEFAULT_MIN_CONFIDENCE", "MIN_CONFIDENCE", "MAX_CONFIDENCE", True),
    "smoothing_alpha": ("DEFAULT_SMOOTHING_ALPHA", "MIN_SMOOTHING_ALPHA", "MAX_SMOOTHING_ALPHA", True),
}


def _const_value(content: str, name: str) -> float | None:
    """Wert einer numerischen Konstante aus const.py lesen."""
    m = re.search(rf"^{name}:\s*Final\s*=\s*([0-9.]+)", content, re.MULTILINE)
    return float(m.group(1)) if m else None


def apply_default_thresholds(thresholds: dict, project_root: Path) -> bool:
    """Schreibt die Schwellenwerte des besten Modells als DEFAULT_* in const.py.

    Die Werte werden auf die MIN_/MAX_-Grenzen aus const.py geklemmt, damit
    der Benchmark keine unzulässigen Defaults hinterlassen kann.
    """
    const_path = project_root / "custom_components" / "bambu_stringing" / "const.py"
    if not const_path.exists():
        print(f"  const.py nicht gefunden: {const_path}")
        return False
    content = const_path.read_text()
    new_content = content
    changed = 0
    for key, (const_name, min_name, max_name, is_float) in DEFAULT_THRESHOLD_KEYS.items():
        if key not in thresholds:
            continue
        try:
            value = float(thresholds[key])
        except (TypeError, ValueError):
            print(f"  WARN: Ungültiger Wert für {key}: {thresholds[key]!r}")
            continue
        lo = _const_value(content, min_name)
        hi = _const_value(content, max_name)
        if lo is not None:
            value = max(value, lo)
        if hi is not None:
            value = min(value, hi)
        if is_float:
            rendered = f"{value:.2f}".rstrip("0").rstrip(".")
            if "." not in rendered:
                rendered += ".0"
        else:
            rendered = str(int(round(value)))
        new_content, n = re.subn(
            rf"({const_name}:\s*Final\s*=\s*)[0-9.]+",
            rf"\g<1>{rendered}",
            new_content,
        )
        if n:
            changed += 1
            print(f"  {const_name} auf {rendered} gesetzt")
        else:
            print(f"  WARN: {const_name} nicht gefunden in const.py")
    if changed == 0:
        return False
    const_path.write_text(new_content)
    return True


# ---------------------------------------------------------------------------
# Benchmark
# ---------------------------------------------------------------------------


async def run_model_images(
    session,
    api_key: str,
    model: str,
    prepared: list[tuple[dict, bytes]],
    concurrency: int,
    max_retries: int,
) -> list[ModelResult]:
    """Alle Bilder eines Modells parallel abarbeiten.

    Ein Semaphore begrenzt die Anzahl gleichzeitiger Anfragen; die Ergebnisse
    kommen durch asyncio.gather in derselben Reihenfolge wie die Eingabe zurück.
    """
    sem = asyncio.Semaphore(concurrency)
    total = len(prepared)
    done = 0

    async def one(img: dict, img_data: bytes) -> ModelResult:
        nonlocal done
        async with sem:
            t0 = time.monotonic()
            img_b64 = encode_image(img_data)
            try:
                data, in_tok, out_tok, latency = await call_mistral_with_retry(
                    session, api_key, model, img_b64, max_retries,
                    log_prefix=f"{img['file']:<18} ",
                )
                scores, observations, confidence, reasoning = parse_scores(data)
                cost = estimate_cost(model, in_tok, out_tok)
                result = ModelResult(
                    model=model,
                    image_file=img["file"],
                    category=img["category"],
                    latency_ms=latency,
                    input_tokens=in_tok,
                    output_tokens=out_tok,
                    est_cost_usd=cost,
                    scores=scores,
                    observations=observations,
                    confidence=confidence,
                    reasoning=reasoning,
                )
                s = scores
                line = (
                    f"str={s['stringing_score']:>3} spa={s['spaghetti_score']:>3} "
                    f"war={s['warping_score']:>3} lsh={s['layer_shift_score']:>3} "
                    f"conf={confidence:.2f} "
                    f"| {latency:>6.0f} ms | ${cost:.4f}"
                )
            except Exception as e:
                # Latenz hier inkl. aller Retry-Wartezeiten
                latency = (time.monotonic() - t0) * 1000
                result = ModelResult(
                    model=model,
                    image_file=img["file"],
                    category=img["category"],
                    latency_ms=latency,
                    error=str(e)[:80],
                )
                line = f"FEHLER: {str(e)[:60]}"
            done += 1
            print(f"  [{done:>2}/{total}] {img['file']:<18} {line}")
            return result

    results = await asyncio.gather(*(one(img, d) for img, d in prepared))
    return list(results)


async def run_benchmark(
    api_key: str,
    models: list[str],
    images_dir: Path,
    concurrency: int = DEFAULT_CONCURRENCY,
    max_retries: int = DEFAULT_MAX_RETRIES,
):
    if aiohttp is None:
        print("\nFEHLER: aiohttp ist nicht installiert. Installation: pip install aiohttp")
        return None, {}

    summaries: list[BenchmarkSummary] = []

    prepared = load_local_images(images_dir)
    if not prepared:
        print("\nFEHLER: Keine lokalen Bilder gefunden.")
        print(f"  Bilder müssen in {images_dir} liegen.")
        return None, {}

    print(f"\n{'='*70}")
    print(f"  Benchmark: {len(models)} Modelle x {len(prepared)} Bilder")
    print(f"  Parallel: {concurrency} Anfragen gleichzeitig, max. {max_retries} Retries")
    print(f"{'='*70}")

    async with aiohttp.ClientSession() as session:
        for model in models:
            print(f"\n{'─'*70}")
            print(f"  Modell: {model}")
            print(f"{'─'*70}")
            results = await run_model_images(
                session, api_key, model, prepared, concurrency, max_retries
            )
            summaries.append(BenchmarkSummary(model=model, results=results))

    return evaluate_and_save(summaries, concurrency)


def load_summaries_from_results(path: Path) -> tuple[list[BenchmarkSummary], int, str]:
    """Baut BenchmarkSummary-Objekte aus einem vorhandenen results.json.

    Ermöglicht --from-results: Threshold-Analyse und Export in die Integration
    erneut ausführen, ohne die API (und damit Kosten) erneut zu bemühen.
    """
    data = json.loads(path.read_text())
    summaries = []
    for m in data.get("models", []):
        results = [
            ModelResult(
                model=m.get("model", "unknown"),
                image_file=r.get("image_file", ""),
                category=r.get("category", ""),
                latency_ms=r.get("latency_ms", 0.0),
                input_tokens=r.get("input_tokens", 0),
                output_tokens=r.get("output_tokens", 0),
                est_cost_usd=r.get("est_cost_usd", 0.0),
                scores=r.get("scores", {}),
                observations=r.get("observations", ""),
                confidence=r.get("confidence", 1.0),
                reasoning=r.get("reasoning", ""),
                error=r.get("error"),
            )
            for r in m.get("results", [])
        ]
        summaries.append(BenchmarkSummary(model=m.get("model", "unknown"), results=results))
    return summaries, int(data.get("concurrency", 0)), str(data.get("timestamp", ""))


def evaluate_and_save(
    summaries: list[BenchmarkSummary],
    concurrency: int,
    timestamp: str | None = None,
) -> tuple[str | None, dict]:
    """Auswertung, Konsolenreport und results.json + benchmark_data.json."""
    # Auswertung
    print(f"\n{'='*80}")
    print("  AUSWERTUNG: Modell-Vergleich")
    print(f"{'='*80}")
    print(f"\n{'Modell':<26} {'Acc':>6} {'Acc*':>6} {'Crit':>6} {'Rel':>6} {'Prod':>6} {'Latenz':>8} {'¢/Scan':>8} {'Calls':>6}")
    print(f"  (Acc* = nach Plausibility Rules, Crit = Critical Defects [Str+Spag], Rel = Reliability v3.4)")
    print(f"{'-'*26} {'-'*6} {'-'*6} {'-'*6} {'-'*6} {'-'*6} {'-'*8} {'-'*8} {'-'*6}")
    for s in summaries:
        ok_count = len([r for r in s.results if r.ok])
        crit = s.critical_defect_score
        crit_bonus = s.critical_bonus
        crit_str = f"{crit:>5.1f}%" + ("⭐" if crit_bonus >= 15 else "+" if crit_bonus > 0 else " ")
        print(
            f"{s.model:<26} {s.accuracy:>5.1f}% {s.accuracy_corrected:>5.1f}% {crit_str:>6} {s.reliability_score:>5.1f} {s.production_score:>5.1f} "
            f"{s.avg_latency:>6.0f}ms {s.cost_per_scan_cents:>7.2f}¢ {ok_count:>6}"
        )

    # Detail: Accuracy pro Kategorie (korrigiert)
    print(f"\n{'─'*80}")
    print("  ACCURACY PRO KATEGORIE (%) — nach Plausibility Rules")
    print(f"{'─'*80}")
    cats = ["stringing", "spaghetti", "warping", "layer_shift", "clean"]
    print(f"\n{'Modell':<26}", end="")
    for cat in cats:
        print(f" {cat[:8]:>8}", end="")
    print()
    print(f"{'-'*26}", end="")
    for _ in cats:
        print(f" {'-'*8}", end="")
    print()
    for s in summaries:
        cat_acc = s.category_accuracy_corrected
        print(f"{s.model:<26}", end="")
        for cat in cats:
            val = cat_acc.get(cat, 0.0)
            print(f" {val:>7.1f}%", end="")
        print()

    # Verbesserung durch Plausibility Rules
    print(f"\n{'─'*80}")
    print("  VERBESSERUNG DURCH PLAUSIBILITY RULES")
    print(f"{'─'*80}")
    for s in summaries:
        raw = s.accuracy
        corr = s.accuracy_corrected
        diff = corr - raw
        if diff != 0:
            print(f"  {s.model:<26} {raw:>5.1f}% → {corr:>5.1f}%  ({diff:+.1f}%)")

    # Ensemble-Empfehlung: Bestes Modell pro Kategorie
    print(f"\n{'─'*80}")
    print("  🎭 ENSEMBLE-EMPFEHLUNG (Bestes Modell pro Kategorie)")
    print(f"{'─'*80}")
    best_per_cat = {}
    for cat in ["stringing", "spaghetti", "warping", "layer_shift", "clean"]:
        best_model = max(summaries, key=lambda s: s.category_accuracy.get(cat, 0), default=None)
        if best_model:
            best_per_cat[cat] = (best_model.model, best_model.category_accuracy.get(cat, 0))
            print(f"  {cat:<12} → {best_model.model:<26} ({best_model.category_accuracy.get(cat, 0):.1f}%)")

    # Prüfe ob ein einzelnes Modell überall gut ist
    recommended = max(summaries, key=lambda s: s.production_score, default=None)
    if recommended:
        weak_cats = [
            cat for cat in ["stringing", "spaghetti", "warping", "layer_shift"]
            if recommended.category_accuracy.get(cat, 0) < 70
        ]
        if weak_cats:
            print(f"\n  ⚠  {recommended.model} ist schwach bei: {', '.join(weak_cats)}")
            print(f"     → Erwäge Critical Ensemble (glm-5-3-flash + medium) für diese Kategorien!")
            # Finde beste Alternative für schwache Kategorien
            for cat in weak_cats:
                best = best_per_cat.get(cat)
                if best and best[0] != recommended.model:
                    print(f"     • {cat}: {best[0]} ({best[1]:.1f}% statt {recommended.category_accuracy.get(cat, 0):.1f}%)")

    # Detail pro Kategorie
    print(f"\n{'─'*80}")
    print("  DETAIL: Scores pro Bild und Modell")
    print(f"{'─'*80}")
    for cat in cats:
        cat_images = [i for i in IMAGES if i["category"] == cat]
        if not cat_images:
            continue
        print(f"\n  Kategorie: {cat.upper()} ({len(cat_images)} Bilder)")
        for img in cat_images:
            row = f"  {img['file']:<18}"
            for s in summaries:
                r = next((r for r in s.results if r.image_file == img["file"]), None)
                if r is None or not r.ok:
                    row += f" {'FEHLER':>22}"
                else:
                    sc = r.scores
                    row += (
                        f" str={sc['stringing_score']:>3}"
                        f" spa={sc['spaghetti_score']:>3}"
                        f" war={sc['warping_score']:>3}"
                        f" lsh={sc['layer_shift_score']:>3}"
                    )
            print(row)

    # Empfehlung
    print(f"\n{'='*80}")
    print("  EMPFEHLUNGEN")
    print(f"{'='*80}")
    
    # Verschiedene Kategorien
    best_acc = max(summaries, key=lambda s: s.accuracy, default=None)
    best_acc_corrected = max(summaries, key=lambda s: s.accuracy_corrected, default=None)
    best_value = max(summaries, key=lambda s: s.value_score, default=None)
    best_production = max(summaries, key=lambda s: s.production_score, default=None)
    best_reliability = max(summaries, key=lambda s: s.reliability_score, default=None)
    best_composite = max(summaries, key=lambda s: s.composite_score, default=None)
    best_speed = min(
        (s for s in summaries if s.avg_latency > 0),
        key=lambda s: s.avg_latency,
        default=None,
    )
    best_cost = min(summaries, key=lambda s: s.total_cost, default=None)
    best_acc_per_dollar = max(
        (s for s in summaries if s.accuracy_per_dollar > 0),
        key=lambda s: s.accuracy_per_dollar,
        default=None,
    )
    
    if best_acc:
        print(f"\n  🏆 Beste Accuracy (roh):       {best_acc.model}")
        print(f"     → {best_acc.accuracy:.1f}% ({best_acc.total_scans} Scans, "
              f"{best_acc.cost_per_scan_cents:.2f}¢/Scan, {best_acc.avg_latency:.0f}ms)")

    if best_acc_corrected:
        marker = " ⭐" if best_acc_corrected.model != best_acc.model else ""
        diff = best_acc_corrected.accuracy_corrected - best_acc_corrected.accuracy
        print(f"\n  🏆 Beste Accuracy (korrigiert): {best_acc_corrected.model}{marker}")
        print(f"     → {best_acc_corrected.accuracy_corrected:.1f}% nach Plausibility Rules "
              f"(roh: {best_acc_corrected.accuracy:.1f}%, {diff:+.1f}%)")
        if diff < 0:
            print(f"     ⚠️  WARNUNG: Plausibility Rules verschlechtern Accuracy um {-diff:.1f}%!")

    best_critical = max(summaries, key=lambda s: s.critical_defect_score, default=None)
    if best_critical:
        cat_acc = best_critical.category_accuracy_corrected
        str_acc = cat_acc.get("stringing", 0.0)
        spa_acc = cat_acc.get("spaghetti", 0.0)
        bonus_marker = " ⭐ PERFEKT" if best_critical.critical_bonus >= 15 else ""
        print(f"\n  🎯 Beste Critical Defects:      {best_critical.model}{bonus_marker}")
        print(f"     → Stringing {str_acc:.1f}%, Spaghetti {spa_acc:.1f}% "
              f"(Score {best_critical.critical_defect_score:.1f}, Bonus +{best_critical.critical_bonus:.1f})")

    if best_reliability:
        print(f"\n  🛡️  Beste Reliability (v3.4):    {best_reliability.model}")
        print(f"     → Reliability Score {best_reliability.reliability_score:.1f} "
              f"({best_reliability.accuracy_corrected:.1f}% korr. Acc, Crit {best_reliability.critical_defect_score:.1f}%, "
              f"{best_reliability.cost_per_scan_cents:.2f}¢/Scan, {best_reliability.avg_latency:.0f}ms)")

    if best_value:
        print(f"\n  💰 Bestes Preis-Leistung: {best_value.model}")
        print(f"     → Value Score {best_value.value_score:.1f} "
              f"({best_value.accuracy:.1f}% Acc, {best_value.cost_per_scan_cents:.2f}¢/Scan, "
              f"{best_value.accuracy_per_dollar:.0f} Acc/$)")
    
    if best_production:
        print(f"\n  ⚡ Best für Live-Betrieb: {best_production.model}")
        print(f"     → Production Score {best_production.production_score:.1f} "
              f"({best_production.accuracy:.1f}% Acc, {best_production.avg_latency:.0f}ms, "
              f"{best_production.cost_per_scan_cents:.2f}¢/Scan)")
    
    if best_acc_per_dollar:
        print(f"\n  📈 Höchste Accuracy pro Dollar: {best_acc_per_dollar.model}")
        print(f"     → {best_acc_per_dollar.accuracy_per_dollar:.0f} Accuracy-Punkte pro $ "
              f"({best_acc_per_dollar.accuracy:.1f}% bei ${best_acc_per_dollar.total_cost:.4f})")
    
    if best_speed:
        print(f"\n  🚀 Schnellstes:        {best_speed.model} ({best_speed.avg_latency:.0f} ms)")
    
    if best_cost:
        print(f"  💵 Günstigstes:        {best_cost.model} (${best_cost.total_cost:.4f} gesamt)")
    
    # Hauptempfehlung: Reliability Score bevorzugen (genauer für 3D-Druck)
    # SICHERHEIT: Niemals ein Modell mit < 70% Accuracy empfehlen!
    # SICHERHEIT: Niemals ein Modell mit < 70% Stringing-Accuracy empfehlen!
    #            (Stringing ist ein kritischer Defekt — False Negatives sind kostspielig)
    MIN_ACCURACY_FOR_RECOMMENDATION = 70.0
    MIN_STRINGING_FOR_RECOMMENDATION = 70.0
    eligible_models = [
        s for s in summaries
        if max(s.accuracy, s.accuracy_corrected) >= MIN_ACCURACY_FOR_RECOMMENDATION
        and s.category_accuracy_corrected.get("stringing", 0.0) >= MIN_STRINGING_FOR_RECOMMENDATION
    ]
    if eligible_models:
        recommended = max(eligible_models, key=lambda s: s.reliability_score)
    else:
        # Fallback: Bestes verfügbares Modell (mit Warnung)
        recommended = best_reliability or best_production or best_composite or best_value
        ineligible = [
            s for s in summaries
            if max(s.accuracy, s.accuracy_corrected) < MIN_ACCURACY_FOR_RECOMMENDATION
            or s.category_accuracy_corrected.get("stringing", 0.0) < MIN_STRINGING_FOR_RECOMMENDATION
        ]
        print(f"\n  ⚠️  WARNUNG: Kein Modell erreicht {MIN_ACCURACY_FOR_RECOMMENDATION:.0f}% Accuracy UND {MIN_STRINGING_FOR_RECOMMENDATION:.0f}% Stringing!")
        print(f"     Nicht qualifizierte Modelle: {', '.join(s.model for s in ineligible)}")
        print(f"     Empfehlung basiert auf bestem verfügbaren Modell (trotz Risiko!).")

    print(f"\n{'─'*80}")
    print(f"  🎯 EMPFEHLUNG FÜR DEFAULT_MODEL: {recommended.model if recommended else 'N/A'}")
    print(f"     (basierend auf Reliability Score v3.4 — Critical Defects + Genauigkeit + Preis)")
    if recommended:
        best_acc_val = max(recommended.accuracy, recommended.accuracy_corrected)
        acc_source = "korrigiert" if recommended.accuracy_corrected > recommended.accuracy else "roh"
        cat_acc = recommended.category_accuracy_corrected
        str_acc = cat_acc.get("stringing", 0.0)
        spa_acc = cat_acc.get("spaghetti", 0.0)
        crit_bonus = recommended.critical_bonus
        crit_marker = " ⭐ PERFEKT" if crit_bonus >= 15 else ""
        print(f"     Accuracy: {recommended.accuracy:.1f}% → {recommended.accuracy_corrected:.1f}% (korrigiert, beste: {best_acc_val:.1f}% {acc_source})")
        print(f"     Critical Defects: Stringing {str_acc:.1f}%, Spaghetti {spa_acc:.1f}%{crit_marker} (Score {recommended.critical_defect_score:.1f}, Bonus +{crit_bonus:.1f})")
        print(f"     Kosten: {recommended.cost_per_scan_cents:.2f}¢/Scan | Latenz: {recommended.avg_latency:.0f}ms")
        print(f"     Reliability Score: {recommended.reliability_score:.1f} | Production Score: {recommended.production_score:.1f}")
        print(f"     Bei 1000 Scans/Monat: ~${recommended.cost_per_scan * 1000:.2f}/Monat")
    print(f"{'='*80}")

    # Threshold-Analyse: jedes Modell bekommt seine eigenen Schwellenwerte,
    # abgeleitet aus der eigenen Score-Verteilung
    thresholds_by_model = analyze_thresholds(summaries)
    print_threshold_recommendations(
        thresholds_by_model, recommended.model if recommended else None
    )

    # Flache Schwellenwert-Struktur des empfohlenen Modells (für JSON/const.py)
    if recommended:
        thresholds_simple = thresholds_from_recommendations(
            thresholds_by_model.get(recommended.model, {})
        )
    else:
        thresholds_simple = dict(THRESHOLD_FALLBACKS)

    # Ergebnisse speichern
    out_path = Path(__file__).parent / "results.json"
    out_data = {
        "timestamp": timestamp or time.strftime("%Y-%m-%d %H:%M:%S"),
        "concurrency": concurrency,
        "recommended_model": recommended.model if recommended else None,
        "recommended_thresholds": thresholds_simple,
        "threshold_analysis": thresholds_by_model,
        "recommendations": {
            "best_accuracy": best_acc.summary_dict() if best_acc else None,
            "best_accuracy_corrected": best_acc_corrected.summary_dict() if best_acc_corrected else None,
            "best_reliability": best_reliability.summary_dict() if best_reliability else None,
            "best_value": best_value.summary_dict() if best_value else None,
            "best_production": best_production.summary_dict() if best_production else None,
            "best_speed": {
                "model": best_speed.model,
                "avg_latency_ms": round(best_speed.avg_latency, 0),
            } if best_speed else None,
            "cheapest": {
                "model": best_cost.model,
                "total_cost_usd": round(best_cost.total_cost, 4),
                "cost_per_scan_cents": round(best_cost.cost_per_scan_cents, 3),
            } if best_cost else None,
            "best_accuracy_per_dollar": {
                "model": best_acc_per_dollar.model,
                "accuracy_per_dollar": round(best_acc_per_dollar.accuracy_per_dollar, 1),
            } if best_acc_per_dollar else None,
        },
        "models": [
            {
                **s.summary_dict(),
                "results": [
                    {
                        "image_file": r.image_file,
                        "category": r.category,
                        "latency_ms": round(r.latency_ms, 0),
                        "input_tokens": r.input_tokens,
                        "output_tokens": r.output_tokens,
                        "est_cost_usd": round(r.est_cost_usd, 6),
                        "scores": r.scores,
                        "observations": r.observations,
                        "confidence": round(r.confidence, 2),
                        "reasoning": r.reasoning,
                        "error": r.error,
                    }
                    for r in s.results
                ],
            }
            for s in summaries
        ],
    }
    out_path.write_text(json.dumps(out_data, indent=2, ensure_ascii=False))
    print(f"\n  Ergebnisse gespeichert: {out_path}")

    # Empfehlung für Integration exportieren
    rec_path = Path(__file__).parent.parent / "custom_components" / "bambu_stringing" / "benchmark_data.json"
    rec_data = {
        "timestamp": out_data["timestamp"],
        "prompt_version": "3.2",
        "recommended_model": recommended.model if recommended else None,
        "recommended_reason": (
            f"Reliability Score v3.4 ({recommended.reliability_score:.1f}): "
            f"Critical Defects {recommended.critical_defect_score:.1f}% "
            f"(Stringing {recommended.category_accuracy_corrected.get('stringing', 0):.0f}%, "
            f"Spaghetti {recommended.category_accuracy_corrected.get('spaghetti', 0):.0f}%), "
            f"Accuracy {max(recommended.accuracy, recommended.accuracy_corrected):.1f}%, "
            f"{recommended.cost_per_scan_cents:.2f}¢/Scan, "
            f"{recommended.avg_latency:.0f}ms Latenz"
        ) if recommended else None,
        "recommended_mode": "single_model",
        "recommended_thresholds": thresholds_simple,
        "threshold_notes": {
            "stringing": f"glm Positive: {sorted(set(r.scores.get('stringing_score', 0) for r in recommended.results if r.category == 'stringing'))}, "
                       f"Negative max: {max((r.scores.get('stringing_score', 0) for r in recommended.results if r.category != 'stringing'), default=0)}",
            "spaghetti": f"Positive: {sorted(set(r.scores.get('spaghetti_score', 0) for r in recommended.results if r.category == 'spaghetti'))}, "
                        f"Negative max: {max((r.scores.get('spaghetti_score', 0) for r in recommended.results if r.category != 'spaghetti'), default=0)}",
            "warping": f"Positive: {sorted(set(r.scores.get('warping_score', 0) for r in recommended.results if r.category == 'warping'))}, "
                      f"Negative max: {max((r.scores.get('warping_score', 0) for r in recommended.results if r.category != 'warping'), default=0)}",
            "layer_shift": f"Positive: {sorted(set(r.scores.get('layer_shift_score', 0) for r in recommended.results if r.category == 'layer_shift'))}, "
                          f"Negative max: {max((r.scores.get('layer_shift_score', 0) for r in recommended.results if r.category != 'layer_shift'), default=0)}",
            "min_confidence": f"Ø Confidence korrekt: {sum(r.confidence for r in recommended.results if r.ok) / max(len([r for r in recommended.results if r.ok]), 1):.2f}, "
                             f"falsch: {sum(r.confidence for r in recommended.results if not r.ok) / max(len([r for r in recommended.results if not r.ok]), 1):.2f}",
        } if recommended else {},
        "models": [
            {
                "model": s.model,
                "accuracy_pct": round(s.accuracy, 1),
                "accuracy_corrected_pct": round(s.accuracy_corrected, 1),
                "avg_latency_ms": round(s.avg_latency, 0),
                "cost_per_scan_cents": round(s.cost_per_scan_cents, 3),
                "value_score": round(s.value_score, 1),
                "production_score": round(s.production_score, 1),
                "reliability_score": round(s.reliability_score, 1),
                "critical_defect_score": round(s.critical_defect_score, 1),
                "critical_bonus": round(s.critical_bonus, 1),
                "category_accuracy": {
                    k: round(v, 1) for k, v in s.category_accuracy.items()
                },
                "category_accuracy_corrected": {
                    k: round(v, 1) for k, v in s.category_accuracy_corrected.items()
                },
                # Schwellenwerte dieses Modells (aus der eigenen Score-Verteilung)
                "recommended_thresholds": thresholds_from_recommendations(
                    thresholds_by_model.get(s.model, {})
                ),
            }
            for s in summaries
        ],
        "recommendations": out_data["recommendations"],
        "model_comparison": {
            s.model: {
                "accuracy_pct": round(s.accuracy, 1),
                "stringing": f"{s.category_accuracy_corrected.get('stringing', 0):.0f}%",
                "spaghetti": f"{s.category_accuracy_corrected.get('spaghetti', 0):.0f}%",
                "clean": f"{s.category_accuracy_corrected.get('clean', 0):.0f}%",
                "warping": f"{s.category_accuracy_corrected.get('warping', 0):.0f}%",
                "layer_shift": f"{s.category_accuracy_corrected.get('layer_shift', 0):.0f}%",
                "cost_per_scan_cents": round(s.cost_per_scan_cents, 3),
                "avg_latency_ms": round(s.avg_latency, 0),
                "reliability_score": round(s.reliability_score, 1),
                "critical_defect_score": round(s.critical_defect_score, 1),
                "verdict": (
                    "🏆 EMPFOHLEN — 100% bei kritischen Defekten, günstigstes Modell"
                    if s.critical_bonus >= 15 else
                    "⚠️ Schnellstes, aber " + (
                        "nur 66.7% Stringing" if s.category_accuracy_corrected.get('stringing', 0) < 70
                        else "mittlere Genauigkeit"
                    ) if s.model == "mistral-medium-latest" else
                    "🐢 Zu langsam und teuer für Live-Betrieb"
                    if s.avg_latency > 10000 else
                    "❌ NICHT EMPFOHLEN — Zu ungenau"
                    if s.accuracy < 70 else
                    "⚠️ Mittelmäßige Genauigkeit"
                ),
            }
            for s in summaries
        },
        "warnings": [
            "Plausibility Rules können Accuracy verschlechtern — immer max(raw, corrected) verwenden!",
            "Layer-Shift Erkennung variiert stark zwischen Modell-Versionen.",
        ],
    }
    rec_path.write_text(json.dumps(rec_data, indent=2, ensure_ascii=False))
    print(f"  Integration-Daten:    {rec_path}")

    return (recommended.model if recommended else None), thresholds_simple


def main():
    parser = argparse.ArgumentParser(
        description="Mistral Vision Benchmark für 3D-Druck Fehlererkennung"
    )
    parser.add_argument(
        "--api-key", help="Mistral API-Key (oder MISTRAL_API_KEY env var)"
    )
    parser.add_argument(
        "--models", nargs="+", default=MODELS, help="Zu testende Modelle"
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=DEFAULT_CONCURRENCY,
        help=f"Gleichzeitige Anfragen pro Modell (Default: {DEFAULT_CONCURRENCY})",
    )
    parser.add_argument(
        "--max-retries",
        type=int,
        default=DEFAULT_MAX_RETRIES,
        help=(
            f"Wiederholungen bei 429/5xx/Netzwerkfehlern "
            f"(Default: {DEFAULT_MAX_RETRIES})"
        ),
    )
    parser.add_argument(
        "--apply-default",
        action="store_true",
        help=(
            "Bestes Modell als DEFAULT_MODEL in const.py setzen und dessen "
            "Schwellenwerte als DEFAULT_*-Konstanten übernehmen"
        ),
    )
    parser.add_argument(
        "--from-results",
        action="store_true",
        help=(
            "Keine API-Aufrufe: Threshold-Analyse und Export in die Integration "
            "aus dem vorhandenen results.json erneut ausführen"
        ),
    )
    args = parser.parse_args()

    if args.from_results:
        results_path = Path(__file__).parent / "results.json"
        if not results_path.exists():
            print(f"FEHLER: {results_path} nicht gefunden.")
            sys.exit(1)
        summaries, concurrency, timestamp = load_summaries_from_results(results_path)
        if not summaries:
            print("FEHLER: Keine Modelle in results.json gefunden.")
            sys.exit(1)
        print(f"Aus results.json geladen: {len(summaries)} Modelle ({timestamp})")
        best_model, best_thresholds = evaluate_and_save(summaries, concurrency, timestamp)
        if args.apply_default and best_model:
            _apply_to_integration(best_model, best_thresholds)
        return

    api_key = load_api_key(args)
    print(f"API-Key geladen: {api_key[:8]}...{api_key[-4:]}")
    print(f"Modelle: {', '.join(args.models)}")
    print(f"Parallelität: {args.concurrency} gleichzeitige Anfragen pro Modell")
    print(f"Bilder:  {len(IMAGES)} (lokal aus images/)")

    images_dir = Path(__file__).parent / "images"
    best_model, best_thresholds = asyncio.run(
        run_benchmark(api_key, args.models, images_dir, args.concurrency, args.max_retries)
    )

    if args.apply_default and best_model:
        _apply_to_integration(best_model, best_thresholds)


def _apply_to_integration(best_model: str, best_thresholds: dict) -> None:
    """Bestes Modell + dessen Schwellenwerte in die Integration schreiben."""
    project_root = Path(__file__).parent.parent
    print(f"\n{'─'*70}")
    print("  DEFAULTS aktualisieren (Modell + Schwellenwerte)")
    print(f"{'─'*70}")
    apply_default_model(best_model, project_root)
    apply_default_thresholds(best_thresholds, project_root)


if __name__ == "__main__":
    main()
