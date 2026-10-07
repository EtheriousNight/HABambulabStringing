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
        "observations",
        "other_defects",
    ):
        assert key in text
    assert "entarteten Druckbilds" in text
    assert "Stützstrukturen" in text
    assert "JSON" in text


def test_prompt_v2_definitions_and_ignore_hints():
    assert prompt.PROMPT_VERSION == "2.0"
    text = prompt.SYSTEM_PROMPT
    assert "abhebende Ränder" in text
    assert "vom Druckbett abhebende Ecken" in text
    assert "versetzter" in text
    assert "Leere Liste" in text
    # ignore hints for common false positives
    assert "gewollte Schrägen" in text
    assert "Elefanten" in text


def test_user_text_without_context():
    text = prompt.build_user_text("")
    assert "JSON-Objekt" in text
    assert "Druckkontext" not in text


def test_user_text_with_context():
    text = prompt.build_user_text("Filament: PLA; Schichthöhe: 0.2 mm")
    assert "Filament: PLA" in text
    assert "JSON-Objekt" in text
