"""Tests for prompt content and user message building."""
from __future__ import annotations

from bs_core import prompt


def test_system_prompt_contains_schema_and_definitions():
    text = prompt.SYSTEM_PROMPT
    for key in (
        "stringing_score",
        "spaghetti_score",
        "warping_score",
        "layer_shift_score",
        "bed_adhesion_failure",
        "confidence",
        "reasoning",
        "observations",
        "other_defects",
    ):
        assert key in text
    assert "JSON" in text


def test_prompt_v3_chain_of_thought():
    assert prompt.PROMPT_VERSION == "3.2"
    text = prompt.SYSTEM_PROMPT
    # Chain-of-Thought Schritte
    assert "SCHRITT 1" in text
    assert "SCHRITT 2" in text
    assert "SCHRITT 3" in text
    assert "SCHRITT 4" in text
    assert "SCHRITT 5" in text
    # Score-Skala
    assert "SCORE-SKALA" in text
    assert "0-10" in text
    assert "91-100" in text
    # Negative Beispiele
    assert "Stützstrukturen" in text
    assert "Brücken" in text
    assert "Negative Beispiele" in text
    # Wichtige Regeln
    assert "AUSSCHLIESSLICH" in text
    assert "MAXIMAL 20" in text


def test_prompt_v31_few_shot_examples():
    """v3.1/v3.2 enthält Few-Shot Examples für schwierige Fälle."""
    text = prompt.SYSTEM_PROMPT
    assert "BEISPIELE" in text
    assert "Beispiel 1" in text
    assert "Beispiel 2" in text
    assert "Beispiel 3" in text
    assert "Beispiel 4" in text
    assert "Beispiel 5" in text
    assert "Beispiel 6" in text
    # Spezifische Beispiele für bekannte Problemfälle
    assert "Temperatur-Türmen" in text or "Temperatur-Türme" in text
    assert "Zylindern" in text or "Zylinder" in text
    assert "Layer Shift" in text
    assert "Spaghetti" in text
    assert "Clean" in text or "Sauberer Druck" in text


def test_prompt_v32_critical_stringing_examples():
    """v3.2 enthält kritische Beispiele für Stringing-vs-Spaghetti-Unterscheidung."""
    text = prompt.SYSTEM_PROMPT
    # Beispiel 7: Zwei Türme mit extremem Stringing (Benchmark: stringing_2.jpg)
    assert "Beispiel 7" in text
    assert "KRITISCH" in text
    assert "EXTREMEM Stringing" in text or "extremes Stringing" in text
    assert "NIEMALS Spaghetti" in text
    # Beispiel 8: Temperatur-Türme mit moderatem Stringing (nicht übersehen)
    assert "Beispiel 8" in text
    assert "nicht übersehen" in text or "nicht uebersehen" in text.lower()


def test_prompt_v3_exclusive_stringing_spaghetti():
    """Stringing und Spaghetti müssen klar getrennt sein."""
    text = prompt.SYSTEM_PROMPT
    assert "Solange das Teil fest steht, ist es NIEMALS Spaghetti" in text
    assert "spaghetti_score darf MAXIMAL 20 sein" in text


def test_user_text_without_context():
    text = prompt.build_user_text("")
    assert "JSON-Objekt" in text
    assert "Druckkontext" not in text
    assert "Schritt für Schritt" in text


def test_user_text_with_context():
    text = prompt.build_user_text("Filament: PLA; Schichthöhe: 0.2 mm")
    assert "Filament: PLA" in text
    assert "JSON-Objekt" in text
    assert "Schritt für Schritt" in text


def test_build_context_string_empty():
    ctx = prompt.build_context_string()
    assert ctx == ""


def test_build_context_string_full():
    ctx = prompt.build_context_string(
        filament_type="PETG",
        nozzle_temp=240,
        bed_temp=70,
        layer_height=0.2,
        print_speed=100,
        current_layer=50,
        total_layers=200,
    )
    assert "PETG" in ctx
    assert "240°C" in ctx
    assert "70°C" in ctx
    assert "0.2mm" in ctx
    assert "100mm/s" in ctx
    assert "50/200" in ctx
    assert "25%" in ctx


def test_build_context_string_filament_hints():
    ctx_petg = prompt.build_context_string(filament_type="PETG")
    assert "neigt zu Stringing" in ctx_petg

    ctx_abs = prompt.build_context_string(filament_type="ABS")
    assert "neigt zu Warping" in ctx_abs

    ctx_tpu = prompt.build_context_string(filament_type="TPU")
    assert "flexibel" in ctx_tpu


def test_build_context_string_temperature_hints():
    ctx_hot = prompt.build_context_string(nozzle_temp=240)
    assert "hoch" in ctx_hot
    assert "mehr Stringing" in ctx_hot

    ctx_cold = prompt.build_context_string(nozzle_temp=190)
    assert "niedrig" in ctx_cold
    assert "Haftungsprobleme" in ctx_cold


def test_build_context_string_layer_phase_hints():
    ctx_early = prompt.build_context_string(current_layer=5, total_layers=200)
    assert "frühe Phase" in ctx_early
    assert "Warping wahrscheinlicher" in ctx_early

    ctx_late = prompt.build_context_string(current_layer=190, total_layers=200)
    assert "späte Phase" in ctx_late
    assert "Layer Shift wahrscheinlicher" in ctx_late
