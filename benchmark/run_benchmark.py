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

    # Ergebnis direkt in const.py übernehmen:
    python3 run_benchmark.py --apply-default

Benötigte Pakete: pip install aiohttp
Bilder: Müssen lokal in benchmark/images/ liegen (siehe images.json).
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import json
import os
import re
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

# ---------------------------------------------------------------------------
# Konfiguration
# ---------------------------------------------------------------------------

MODELS = [
    "mistral-large-4",
    "mistral-large-latest",
    "mistral-medium-latest",
    "mistral-small-latest",
]

# Preise pro 1M Tokens (Mistral API, https://mistral.ai/pricing/api, Stand 2026-10-07)
# mistral-large-4: Sale-Preis (Original: $1.36 Input / $4.18 Output)
# *-latest-Aliase zeigen aktuell auf Large 3 / Medium 3.5 / Small 4
PRICING = {
    "mistral-large-4": {"input": 0.68, "output": 2.09},
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
    # --- Spaghetti (6 Bilder) ---
    {"file": "spaghetti_1.jpg", "category": "spaghetti",
     "expected": {"spaghetti_score_min": 60, "stringing_score_max": 50},
     "desc": "Reddit: Spaghetti Failure Bambu"},
    {"file": "spaghetti_2.jpg", "category": "spaghetti",
     "expected": {"spaghetti_score_min": 60, "stringing_score_max": 50},
     "desc": "Reddit: Spaghetti Chaos"},
    {"file": "spaghetti_3.jpg", "category": "spaghetti",
     "expected": {"spaghetti_score_min": 50, "stringing_score_max": 50},
     "desc": "Reddit: Spaghetti GIF"},
    {"file": "spaghetti_4.jpg", "category": "spaghetti",
     "expected": {"spaghetti_score_min": 60, "stringing_score_max": 50},
     "desc": "Reddit: Spaghetti 3D prints"},
    {"file": "spaghetti_5.jpg", "category": "spaghetti",
     "expected": {"spaghetti_score_min": 60, "stringing_score_max": 50},
     "desc": "Reddit: Spaghetti Druckbett"},
    {"file": "spaghetti_6.jpg", "category": "spaghetti",
     "expected": {"spaghetti_score_min": 50, "stringing_score_max": 50},
     "desc": "Bambu Forum: Spaghetti"},
    # --- Warping (2 Bilder) ---
    {"file": "warping_1.webp", "category": "warping",
     "expected": {"warping_score_min": 40, "spaghetti_score_max": 30},
     "desc": "Creality: Warping abhebende Ecken"},
    {"file": "warping_2.jpg", "category": "warping",
     "expected": {"warping_score_min": 30, "spaghetti_score_max": 30},
     "desc": "3DX: Warping Verzug"},
    # --- Layer Shift (4 Bilder) ---
    {"file": "layer_shift_1.jpg", "category": "layer_shift",
     "expected": {"layer_shift_score_min": 50, "spaghetti_score_max": 30},
     "desc": "Prusa KB: Layer Shifting"},
    {"file": "layer_shift_2.png", "category": "layer_shift",
     "expected": {"layer_shift_score_min": 50, "spaghetti_score_max": 30},
     "desc": "Creality: Layer Shift"},
    {"file": "layer_shift_3.jpg", "category": "layer_shift",
     "expected": {"layer_shift_score_min": 40, "spaghetti_score_max": 30},
     "desc": "3DSourced: Layer Shifting"},
    {"file": "layer_shift_4.jpg", "category": "layer_shift",
     "expected": {"layer_shift_score_min": 40, "spaghetti_score_max": 30},
     "desc": "Sovol: Layer Shift"},
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

# Derselbe System-Prompt wie in der Integration (core/prompt.py v2.0)
SYSTEM_PROMPT = """Du bist ein Inspektor für FDM-3D-Druck. Du erhältst ein Bild aus der Druckkammer eines Bambu Lab P1S. Bewerte ausschließlich das Druckbild.

Antworte ausschließlich als JSON:
{
  "stringing_score": <0-100>,
  "spaghetti_score": <0-100>,
  "warping_score": <0-100>,
  "layer_shift_score": <0-100>,
  "bed_adhesion_failure": <true|false>,
  "observations": "<max. 2 Sätze, deutsch>",
  "other_defects": ["<max. 3 kurze deutsche Beschreibungen>"]
}

Definitionen:
- stringing_score: Schweregrad feiner Filamentfäden oder Spinnweben zwischen oder auf Strukturen. 0 = sauber. Typische Ursache ist Oozing beim Travel; nicht verwechseln mit Stützstrukturen, gewollten Brücken oder dünnen Design-Features.
- spaghetti_score: Wahrscheinlichkeit eines entarteten Druckbilds (Materialklumpen, vom Bett gelöste Teile, Nest).
- warping_score: Schweregrad von Verzug: abhebende Ränder, schüsselartig gewölbte Flächen, vom Druckbett abhebende Ecken. 0 = flach aufliegend.
- layer_shift_score: Wahrscheinlichkeit versetzter oder wandernder Layer (schief verschobene Ebenen, Stufen quer zum Druckbild). 0 = keine Versätze.
- bed_adhesion_failure: true, wenn Teile sichtbar vom Druckbett gelöst sind.
- other_defects: Kurze Liste weiterer Defekte (max. 3), z. B. Unterextrusion, Blobs, Z-Scarring, Zittrige Kanten. Leere Liste, wenn nichts auffällt.
- Ignoriere: Beleuchtung, Spiegelungen, Werkzeugkopf, die Bauteil-Geometrie selbst, Abschattungen durch den Druckkopf, gewollte Schrägen oder geneigte Flächen des Modells (kein Warping), Texturierungen der Druckplatte (z. B. Elefanten-Protectivfolie oder PUR-Folie) und den minimalen First-Layer-Rand."""

USER_TEXT = (
    "Bewerte das beigefügte Kammerbild gemäß der Vorgaben. "
    "Antworte nur mit dem JSON-Objekt."
)

MISTRAL_CHAT_URL = "https://api.mistral.ai/v1/chat/completions"

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
    def accuracy(self) -> float:
        if not self.results:
            return 0.0
        correct = 0
        for r in self.results:
            if not r.ok:
                continue
            img = next((i for i in IMAGES if i["file"] == r.image_file), None)
            if img is None:
                continue
            exp = img["expected"]
            s = r.scores
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
                correct += 1
        total = len([r for r in self.results if r.ok])
        return correct / total * 100 if total else 0.0

    @property
    def composite_score(self) -> float:
        """Gewichteter Score: 60% Accuracy, 25% Speed, 15% Cost (normalisiert)."""
        if not self.results:
            return 0.0
        acc = self.accuracy
        # Speed: niedrigere Latenz = besser (normalisiert auf 0-100)
        speed = max(0, 100 - self.avg_latency / 50) if self.avg_latency > 0 else 0
        # Cost: niedrigere Kosten = besser (normalisiert auf 0-100)
        cost = max(0, 100 - self.total_cost * 10000) if self.total_cost > 0 else 100
        return acc * 0.6 + speed * 0.25 + cost * 0.15


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


async def call_mistral(session, api_key: str, model: str, image_b64: str):
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
    # 120s: Reasoning-Modelle (mistral-large-4) brauchen beim Cold Start > 60s
    async with session.post(
        MISTRAL_CHAT_URL, headers=headers, json=payload, timeout=120
    ) as resp:
        data = await resp.json(content_type=None)
        if resp.status != 200:
            raise RuntimeError(f"HTTP {resp.status}: {data}")
        usage = data.get("usage", {})
        return data, usage.get("prompt_tokens", 0), usage.get("completion_tokens", 0)


def parse_scores(data: dict) -> tuple[dict, str]:
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
    return scores, observations


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
    new_content = re.sub(pattern, rf'\g<1>{model}\g<2>', content)
    if new_content == content:
        print(f"  WARN: DEFAULT_MODEL nicht gefunden in const.py")
        return False
    const_path.write_text(new_content)
    print(f"  DEFAULT_MODEL auf '{model}' gesetzt in const.py")
    return True


# ---------------------------------------------------------------------------
# Benchmark
# ---------------------------------------------------------------------------


async def run_benchmark(api_key: str, models: list[str], images_dir: Path):
    import aiohttp

    summaries: list[BenchmarkSummary] = []

    prepared = load_local_images(images_dir)
    if not prepared:
        print("\nFEHLER: Keine lokalen Bilder gefunden.")
        print(f"  Bilder müssen in {images_dir} liegen.")
        return

    print(f"\n{'='*70}")
    print(f"  Benchmark: {len(models)} Modelle x {len(prepared)} Bilder")
    print(f"{'='*70}")

    async with aiohttp.ClientSession() as session:
        for model in models:
            print(f"\n{'─'*70}")
            print(f"  Modell: {model}")
            print(f"{'─'*70}")
            summary = BenchmarkSummary(model=model)

            for img, img_data in prepared:
                img_b64 = encode_image(img_data)
                t0 = time.monotonic()
                try:
                    data, in_tok, out_tok = await call_mistral(
                        session, api_key, model, img_b64
                    )
                    latency = (time.monotonic() - t0) * 1000
                    scores, observations = parse_scores(data)
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
                    )
                    s = scores
                    print(
                        f"  {img['file']:<18} "
                        f"str={s['stringing_score']:>3} spa={s['spaghetti_score']:>3} "
                        f"war={s['warping_score']:>3} lsh={s['layer_shift_score']:>3} "
                        f"| {latency:>6.0f} ms | ${cost:.4f}"
                    )
                except Exception as e:
                    latency = (time.monotonic() - t0) * 1000
                    result = ModelResult(
                        model=model,
                        image_file=img["file"],
                        category=img["category"],
                        latency_ms=latency,
                        error=str(e)[:80],
                    )
                    print(f"  {img['file']:<18} FEHLER: {str(e)[:60]}")

                summary.results.append(result)
                await asyncio.sleep(0.3)

            summaries.append(summary)

    # Auswertung
    print(f"\n{'='*70}")
    print("  AUSWERTUNG")
    print(f"{'='*70}")
    print(f"\n{'Modell':<28} {'Accuracy':>9} {'Composite':>10} {'Avg Latenz':>11} {'Kosten':>10} {'Calls':>6}")
    print(f"{'-'*28} {'-'*9} {'-'*10} {'-'*11} {'-'*10} {'-'*6}")
    for s in summaries:
        ok_count = len([r for r in s.results if r.ok])
        print(
            f"{s.model:<28} {s.accuracy:>8.1f}% {s.composite_score:>9.1f} "
            f"{s.avg_latency:>9.0f} ms ${s.total_cost:>8.4f} {ok_count:>6}"
        )

    # Detail pro Kategorie
    print(f"\n{'─'*70}")
    print("  DETAIL: Scores pro Bild und Modell")
    print(f"{'─'*70}")
    categories = ["stringing", "spaghetti", "warping", "layer_shift", "clean"]
    for cat in categories:
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
    print(f"\n{'='*70}")
    print("  EMPFEHLUNG")
    print(f"{'='*70}")
    best_acc = max(summaries, key=lambda s: s.accuracy, default=None)
    best_speed = min(
        (s for s in summaries if s.avg_latency > 0),
        key=lambda s: s.avg_latency,
        default=None,
    )
    best_cost = min(summaries, key=lambda s: s.total_cost, default=None)
    best_composite = max(summaries, key=lambda s: s.composite_score, default=None)
    if best_acc:
        print(f"  Beste Accuracy:   {best_acc.model} ({best_acc.accuracy:.1f}%)")
    if best_speed:
        print(f"  Schnellstes:      {best_speed.model} ({best_speed.avg_latency:.0f} ms)")
    if best_cost:
        print(f"  Günstigste:       {best_cost.model} (${best_cost.total_cost:.4f})")
    if best_composite:
        print(f"  Bestes Composite: {best_composite.model} ({best_composite.composite_score:.1f})")
        print(f"\n  → Empfohlenes DEFAULT_MODEL: {best_composite.model}")

    # Ergebnisse speichern
    out_path = Path(__file__).parent / "results.json"
    out_data = {
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "recommended_model": best_composite.model if best_composite else None,
        "models": [
            {
                "model": s.model,
                "accuracy_pct": round(s.accuracy, 1),
                "composite_score": round(s.composite_score, 1),
                "avg_latency_ms": round(s.avg_latency, 0),
                "total_cost_usd": round(s.total_cost, 4),
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

    return best_composite.model if best_composite else None


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
        "--apply-default",
        action="store_true",
        help="Bestes Modell automatisch als DEFAULT_MODEL in const.py setzen",
    )
    args = parser.parse_args()

    api_key = load_api_key(args)
    print(f"API-Key geladen: {api_key[:8]}...{api_key[-4:]}")
    print(f"Modelle: {', '.join(args.models)}")
    print(f"Bilder:  {len(IMAGES)} (lokal aus images/)")

    images_dir = Path(__file__).parent / "images"
    best_model = asyncio.run(run_benchmark(api_key, args.models, images_dir))

    if args.apply_default and best_model:
        project_root = Path(__file__).parent.parent
        print(f"\n{'─'*70}")
        print("  DEFAULT_MODEL aktualisieren")
        print(f"{'─'*70}")
        apply_default_model(best_model, project_root)


if __name__ == "__main__":
    main()
