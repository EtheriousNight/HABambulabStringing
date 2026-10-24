"""Tests for the Mistral client: payload, parsing, validation, plausibility."""
from __future__ import annotations

import base64
import json

import pytest

from bs_core import mistral
from bs_core.mistral import AnalysisError, AnalysisResult


VALID_ANSWER = {
    "stringing_score": 42,
    "spaghetti_score": 5,
    "bed_adhesion_failure": False,
    "observations": "Vereinzelte feine Fäden zwischen den Strukturen.",
}


def api_response(content) -> dict:
    if isinstance(content, str):
        content_str = content
    else:
        content_str = json.dumps(content, ensure_ascii=False)
    return {"choices": [{"message": {"content": content_str}}]}


# -- request building -----------------------------------------------------------


def test_build_request_structure():
    request = mistral.build_request(
        api_key="key123",
        model="pixtral-12b-latest",
        image_b64="QUJD",
        context="PLA; Schichthöhe: 0.2 mm",
    )
    assert request.url == "https://api.mistral.ai/v1/chat/completions"
    assert request.headers["Authorization"] == "Bearer key123"
    payload = request.payload
    assert payload["model"] == "pixtral-12b-latest"
    assert payload["response_format"] == {"type": "json_object"}
    system, user = payload["messages"]
    assert system["role"] == "system"
    assert "stringing_score" in system["content"]
    content = user["content"]
    assert content[0]["type"] == "text"
    assert "PLA" in content[0]["text"]
    assert content[1]["image_url"]["url"] == "data:image/jpeg;base64,QUJD"


def test_encode_image_roundtrip():
    frame = b"\xff\xd8\xff\xd9fake"
    assert base64.b64decode(mistral.encode_image(frame)) == frame


# -- parsing ---------------------------------------------------------------------


def test_parse_valid_response():
    parsed = mistral.parse_response(api_response(VALID_ANSWER))
    assert parsed == AnalysisResult(
        stringing_score=42,
        spaghetti_score=5,
        bed_adhesion_failure=False,
        observations=VALID_ANSWER["observations"],
    )


def test_parse_markdown_wrapped_json():
    content = "```json\n" + json.dumps(VALID_ANSWER) + "\n```"
    parsed = mistral.parse_response(api_response(content))
    assert parsed.stringing_score == 42


def test_parse_content_as_part_list():
    data = {
        "choices": [
            {"message": {"content": [{"type": "text", "text": json.dumps(VALID_ANSWER)}]}}
        ]
    }
    parsed = mistral.parse_response(data)
    assert parsed.spaghetti_score == 5


@pytest.mark.parametrize(
    "payload",
    [
        {},  # no choices
        {"choices": []},
        {"choices": [{"message": {}}]},
        {"choices": [{"message": {"content": "not json at all"}}]},
    ],
)
def test_parse_rejects_broken_responses(payload):
    with pytest.raises(AnalysisError) as exc:
        mistral.parse_response(payload)
    assert exc.value.kind == mistral.KIND_PARSE


@pytest.mark.parametrize(
    "answer",
    [
        {**VALID_ANSWER, "stringing_score": 101},
        {**VALID_ANSWER, "stringing_score": -1},
        {**VALID_ANSWER, "stringing_score": "hoch"},
        {**VALID_ANSWER, "bed_adhesion_failure": "ja"},
        {**VALID_ANSWER, "observations": ""},
    ],
)
def test_parse_rejects_schema_violations(answer):
    with pytest.raises(AnalysisError) as exc:
        mistral.parse_response(api_response(answer))
    assert exc.value.kind == mistral.KIND_PARSE


def test_parse_missing_keys():
    with pytest.raises(AnalysisError) as exc:
        mistral.parse_response(api_response({"stringing_score": 10}))
    assert "spaghetti_score" in str(exc.value)


# -- prompt v2 fields -------------------------------------------------------------

V2_ANSWER = {
    **VALID_ANSWER,
    "warping_score": 12,
    "layer_shift_score": 3,
    "other_defects": ["Unterextrusion an dünnen Wänden", "Blobs am Turm"],
}


def test_parse_v2_response_with_new_fields():
    parsed = mistral.parse_response(api_response(V2_ANSWER))
    assert parsed.warping_score == 12
    assert parsed.layer_shift_score == 3
    assert parsed.other_defects == (
        "Unterextrusion an dünnen Wänden",
        "Blobs am Turm",
    )


def test_parse_v1_answer_still_valid_with_defaults():
    """Frames from an older prompt/model without the new fields parse fine."""
    parsed = mistral.parse_response(api_response(VALID_ANSWER))
    assert parsed.warping_score == 0
    assert parsed.layer_shift_score == 0
    assert parsed.other_defects == ()


@pytest.mark.parametrize(
    "answer",
    [
        {**V2_ANSWER, "warping_score": 150},
        {**V2_ANSWER, "layer_shift_score": "stark"},
        {**V2_ANSWER, "other_defects": "keine"},  # string wrapped into list
    ],
)
def test_parse_v2_score_validation(answer):
    if answer["other_defects"] == "keine":
        parsed = mistral.parse_response(api_response(answer))
        assert parsed.other_defects == ("keine",)
    else:
        with pytest.raises(AnalysisError) as exc:
            mistral.parse_response(api_response(answer))
        assert exc.value.kind == mistral.KIND_PARSE


def test_parse_other_defects_truncated_and_capped():
    answer = {
        **VALID_ANSWER,
        "other_defects": ["", "  Z-Scarring  ", "a" * 200, "dritter", "vierter"],
    }
    parsed = mistral.parse_response(api_response(answer))
    assert parsed.other_defects == ("Z-Scarring", "a" * 80)


def test_parse_other_defects_none_and_invalid():
    parsed = mistral.parse_response(api_response({**VALID_ANSWER, "other_defects": None}))
    assert parsed.other_defects == ()
    with pytest.raises(AnalysisError) as exc:
        mistral.parse_response(api_response({**VALID_ANSWER, "other_defects": 42}))
    assert exc.value.kind == mistral.KIND_PARSE


# -- plausibility ----------------------------------------------------------------


def test_plausibility_rejects_contradicting_observations():
    result = AnalysisResult(0, 0, False, "Deutliche Spaghetti auf dem Bett.")
    with pytest.raises(AnalysisError) as exc:
        mistral.check_plausibility(result)
    assert exc.value.kind == mistral.KIND_PLAUSIBILITY


def test_plausibility_accepts_consistent_answers():
    # "Sauberer Druck" mit niedrigen Scores triggert Rule 4 → Scores werden auf 0 gesetzt
    result = AnalysisResult(5, 0, False, "Sauberer Druck, keine Auffälligkeiten.")
    corrected = mistral.check_plausibility(result)
    assert corrected.stringing_score == 0  # Rule 4: clean confirmed
    assert corrected.spaghetti_score == 0

    # Zweiter Fall: kein Clean-Keyword, keine Regel greift → Ergebnis unverändert
    flagged = AnalysisResult(60, 10, False, "Viele Fäden zwischen den Türmen.")
    corrected2 = mistral.check_plausibility(flagged)
    assert corrected2.stringing_score == 60
    assert corrected2.spaghetti_score == 10


def test_plausibility_rejects_warping_and_layer_shift_contradictions():
    with pytest.raises(AnalysisError) as exc:
        mistral.check_plausibility(
            AnalysisResult(0, 0, False, "Ränder deutlich abgehoben (Warping).")
        )
    assert exc.value.kind == mistral.KIND_PLAUSIBILITY
    with pytest.raises(AnalysisError):
        mistral.check_plausibility(
            AnalysisResult(0, 0, False, "Layer deutlich versetzt.")
        )


def test_plausibility_accepts_when_new_scores_back_observations():
    result = AnalysisResult(
        0, 0, False, "Ränder deutlich abgehoben (Warping).", warping_score=70
    )
    corrected = mistral.check_plausibility(result)
    assert corrected.warping_score == 70

    shifted = AnalysisResult(
        0, 0, False, "Layer deutlich versetzt.", layer_shift_score=80
    )
    corrected2 = mistral.check_plausibility(shifted)
    assert corrected2.layer_shift_score == 80


# -- analyze_frame ---------------------------------------------------------------


async def test_analyze_frame_success():
    async def post_json(url, *, headers, payload):
        assert "chat/completions" in url
        return api_response(VALID_ANSWER)

    result = await mistral.analyze_frame(
        post_json, api_key="k", model="m", frame=b"\xff\xd8...", context="PLA"
    )
    assert result.stringing_score == 42


async def test_analyze_frame_api_error_wrapped():
    async def post_json(url, *, headers, payload):
        raise RuntimeError("connection reset")

    with pytest.raises(AnalysisError) as exc:
        await mistral.analyze_frame(post_json, api_key="k", model="m", frame=b"x")
    assert exc.value.kind == mistral.KIND_API


async def test_analyze_frame_parse_error_wrapped():
    async def post_json(url, *, headers, payload):
        return {"choices": [{"message": {"content": "garbage"}}]}

    with pytest.raises(AnalysisError) as exc:
        await mistral.analyze_frame(post_json, api_key="k", model="m", frame=b"x")
    assert exc.value.kind == mistral.KIND_PARSE


# -- prompt v3.0: confidence & reasoning -----------------------------------------

V3_ANSWER = {
    **VALID_ANSWER,
    "warping_score": 0,
    "layer_shift_score": 0,
    "confidence": 0.85,
    "reasoning": "Teil steht fest, deutliche Fäden zwischen Türmen sichtbar",
    "other_defects": [],
}


def test_parse_v3_response_with_confidence_and_reasoning():
    parsed = mistral.parse_response(api_response(V3_ANSWER))
    assert parsed.confidence == 0.85
    assert "Teil steht fest" in parsed.reasoning


def test_parse_v3_confidence_defaults_to_1():
    """Older responses without confidence field default to 1.0."""
    parsed = mistral.parse_response(api_response(VALID_ANSWER))
    assert parsed.confidence == 1.0
    assert parsed.reasoning == ""


def test_parse_v3_confidence_clamped():
    """Confidence outside 0-1 range is clamped."""
    answer = {**V3_ANSWER, "confidence": 1.5}
    parsed = mistral.parse_response(api_response(answer))
    assert parsed.confidence == 1.0

    answer = {**V3_ANSWER, "confidence": -0.5}
    parsed = mistral.parse_response(api_response(answer))
    assert parsed.confidence == 0.0


def test_parse_v3_confidence_invalid_type():
    """Non-numeric confidence defaults to 1.0."""
    answer = {**V3_ANSWER, "confidence": "high"}
    parsed = mistral.parse_response(api_response(answer))
    assert parsed.confidence == 1.0


def test_parse_v3_reasoning_truncated():
    """Reasoning is truncated to 200 chars."""
    answer = {**V3_ANSWER, "reasoning": "x" * 300}
    parsed = mistral.parse_response(api_response(answer))
    assert len(parsed.reasoning) == 200


# -- plausibility rules (v3.0) -----------------------------------------------------


def test_plausibility_rule1_spaghetti_without_adhesion_corrected():
    """Spaghetti > 60 without bed_adhesion_failure + stringing > 40 → stringing wins."""
    result = AnalysisResult(
        stringing_score=85,
        spaghetti_score=90,
        bed_adhesion_failure=False,
        observations="Deutliche Fäden zwischen den Türmen",
        confidence=0.8,
    )
    corrected = mistral.apply_plausibility_rules(result)
    assert corrected.spaghetti_score <= 30
    assert corrected.stringing_score >= 70


def test_plausibility_rule2_both_high_with_adhesion_failure():
    """Both high + bed_adhesion_failure → spaghetti wins, stringing reduced."""
    result = AnalysisResult(
        stringing_score=85,
        spaghetti_score=90,
        bed_adhesion_failure=True,
        observations="Katastrophaler Fehler, Teil gelöst",
        confidence=0.9,
    )
    corrected = mistral.apply_plausibility_rules(result)
    assert corrected.stringing_score <= 50
    assert corrected.spaghetti_score == 90


def test_plausibility_rule2_both_high_without_adhesion_failure():
    """Both high without bed_adhesion_failure → stringing wins."""
    result = AnalysisResult(
        stringing_score=80,
        spaghetti_score=85,
        bed_adhesion_failure=False,
        observations="Extreme Fäden zwischen den Strukturen",
        confidence=0.8,
    )
    corrected = mistral.apply_plausibility_rules(result)
    assert corrected.spaghetti_score <= 30
    assert corrected.stringing_score >= 70


def test_plausibility_rule3_layer_shift_and_stringing_keywords():
    """Layer shift + stringing high → keyword-based decision."""
    # Stringing keywords in observations → layer_shift reduced
    result = AnalysisResult(
        stringing_score=80,
        spaghetti_score=0,
        bed_adhesion_failure=False,
        observations="Deutliche Fäden und Spinnweben zwischen den Türmen",
        layer_shift_score=85,
        confidence=0.7,
    )
    corrected = mistral.apply_plausibility_rules(result)
    assert corrected.layer_shift_score <= 40

    # Layer shift keywords in observations → stringing reduced
    result2 = AnalysisResult(
        stringing_score=80,
        spaghetti_score=0,
        bed_adhesion_failure=False,
        observations="Deutliche Stufen und Versatz in den Schichten",
        layer_shift_score=85,
        confidence=0.7,
    )
    corrected2 = mistral.apply_plausibility_rules(result2)
    assert corrected2.stringing_score <= 30


def test_plausibility_rule4_clean_with_clean_keywords():
    """All scores low + 'sauber' in observations → all scores set to 0."""
    result = AnalysisResult(
        stringing_score=10,
        spaghetti_score=5,
        bed_adhesion_failure=False,
        observations="Der Druck ist sauber und fehlerfrei",
        warping_score=8,
        layer_shift_score=3,
        confidence=0.95,
    )
    corrected = mistral.apply_plausibility_rules(result)
    assert corrected.stringing_score == 0
    assert corrected.spaghetti_score == 0
    assert corrected.warping_score == 0
    assert corrected.layer_shift_score == 0


def test_plausibility_rule5_spaghetti_without_adhesion_or_stringing():
    """Spaghetti > 50 without adhesion failure and low stringing → reduced."""
    result = AnalysisResult(
        stringing_score=10,
        spaghetti_score=70,
        bed_adhesion_failure=False,
        observations="Materialklumpen auf dem Bett",
        confidence=0.6,
    )
    corrected = mistral.apply_plausibility_rules(result)
    assert corrected.spaghetti_score <= 30


def test_plausibility_rule6_spaghetti_with_standing_towers():
    """Rule 6 (v3.2): Spaghetti > 70 but observations mention standing towers
    → misclassification, correct to stringing (Benchmark: stringing_2.jpg)."""
    result = AnalysisResult(
        stringing_score=0,
        spaghetti_score=95,
        bed_adhesion_failure=True,  # Model incorrectly thinks adhesion failed
        observations="Zwei zylindrische Türme stehen fest auf der Platte, dazwischen dichter Fadenteppich",
        confidence=1.0,
        reasoning="Teil vollständig vom Bett gelöst, chaotisches Filamentnest sichtbar",
    )
    corrected = mistral.apply_plausibility_rules(result)
    # Should be corrected: spaghetti reduced, stringing increased
    assert corrected.spaghetti_score <= 25
    assert corrected.stringing_score >= 75
    assert corrected.bed_adhesion_failure is False


def test_plausibility_rule6_spaghetti_with_standing_towers_v32():
    """Rule 6 (v3.2 konservativ): Spaghetti > 80 + 2+ stehende Indikatoren → Korrektur."""
    result = AnalysisResult(
        stringing_score=5,
        spaghetti_score=90,
        bed_adhesion_failure=True,
        observations="Zwei zylindrische Türme stehen fest und intakt auf der Grundplatte, dazwischen Spinnweben",
        confidence=0.9,
        reasoning="Nest erkannt",
    )
    corrected = mistral.apply_plausibility_rules(result)
    # "Türme" + "stehen fest" + "intakt" + "Grundplatte" = 4 Indikatoren, keine Nest-Wörter
    assert corrected.spaghetti_score <= 25
    assert corrected.stringing_score >= 75


def test_plausibility_rule6_no_correction_with_nest_keywords():
    """Rule 6 (v3.2): Bei Nest-Keywords wie 'verheddert' NICHT korrigieren."""
    result = AnalysisResult(
        stringing_score=5,
        spaghetti_score=90,
        bed_adhesion_failure=True,
        observations="Zylinder haftet noch, aber verheddertes Nest aus Filament bedeckt das Bett",
        confidence=0.9,
        reasoning="Spaghetti erkannt",
    )
    corrected = mistral.apply_plausibility_rules(result)
    # "verheddert" und "Nest" sind Nest-Indikatoren → keine Korrektur
    assert corrected.spaghetti_score >= 85


def test_plausibility_rule6_no_correction_below_80():
    """Rule 6 (v3.2): Nur bei spaghetti > 80 triggern, nicht bei 75."""
    result = AnalysisResult(
        stringing_score=5,
        spaghetti_score=75,
        bed_adhesion_failure=True,
        observations="Zwei Türme stehen fest und intakt auf der Grundplatte",
        confidence=0.9,
        reasoning="Unsicher",
    )
    corrected = mistral.apply_plausibility_rules(result)
    # spaghetti=75 < 80 → Rule 6 nicht aktiv
    assert corrected.spaghetti_score == 75


def test_plausibility_rule6_no_correction_with_high_stringing():
    """Rule 6 (v3.2): Nur bei stringing < 20 triggern."""
    result = AnalysisResult(
        stringing_score=50,
        spaghetti_score=90,
        bed_adhesion_failure=True,
        observations="Zwei Türme stehen fest und intakt auf der Grundplatte",
        confidence=0.9,
        reasoning="Beides erkannt",
    )
    corrected = mistral.apply_plausibility_rules(result)
    # stringing=50 >= 20 → Rule 6 nicht aktiv
    assert corrected.spaghetti_score == 90


def test_plausibility_rule7_stringing_zero_with_faden_keywords():
    """Rule 7 (v3.2): Stringing score 0 but observations mention Fäden → boost."""
    result = AnalysisResult(
        stringing_score=0,
        spaghetti_score=0,
        bed_adhesion_failure=False,
        observations="Mehrere Türme mit feinen Filamentfäden zwischen den Spitzen",
        confidence=1.0,
        reasoning="Keine Defekte sichtbar",
    )
    corrected = mistral.apply_plausibility_rules(result)
    # Stringing should be boosted because "Fäden" mentioned (no negation)
    assert corrected.stringing_score >= 40


def test_plausibility_rule7_stringing_zero_with_spinnweben():
    """Rule 7: 'Spinnweben' keyword also triggers boost."""
    result = AnalysisResult(
        stringing_score=0,
        spaghetti_score=10,
        bed_adhesion_failure=False,
        observations="Dichte Spinnweben zwischen den Strukturen sichtbar",
        confidence=0.9,
        reasoning="Leichte Spuren",
    )
    corrected = mistral.apply_plausibility_rules(result)
    assert corrected.stringing_score >= 40


def test_plausibility_rule7_no_boost_with_negation_keine_faeden():
    """Rule 7 (v3.2 FIX): 'keine Fäden' darf NICHT triggern!"""
    result = AnalysisResult(
        stringing_score=0,
        spaghetti_score=0,
        bed_adhesion_failure=False,
        observations="Alle Teile stehen fest, keine Fäden oder Ablösungen erkennbar",
        confidence=1.0,
        reasoning="Sauberer Druck",
    )
    corrected = mistral.apply_plausibility_rules(result)
    # "keine Fäden" enthält Negation → kein Boost!
    assert corrected.stringing_score < 40


def test_plausibility_rule7_no_boost_with_negation_sauber():
    """Rule 7 (v3.2 FIX): 'sauber', 'makellos' etc. dürfen NICHT triggern."""
    result = AnalysisResult(
        stringing_score=0,
        spaghetti_score=0,
        bed_adhesion_failure=False,
        observations="Sauberer Druck mit gleichmäßigen Schichten, makellos und fehlerfrei",
        confidence=1.0,
        reasoning="Keine Defekte",
    )
    corrected = mistral.apply_plausibility_rules(result)
    assert corrected.stringing_score < 40


def test_plausibility_rule7_no_boost_with_negation_ohne():
    """Rule 7 (v3.2 FIX): 'ohne Fäden' darf NICHT triggern."""
    result = AnalysisResult(
        stringing_score=0,
        spaghetti_score=0,
        bed_adhesion_failure=False,
        observations="Teil haftet fest, ohne Fäden oder Spinnweben",
        confidence=1.0,
        reasoning="Clean",
    )
    corrected = mistral.apply_plausibility_rules(result)
    assert corrected.stringing_score < 40


def test_plausibility_rule7_no_boost_when_high_spaghetti():
    """Rule 7 should not boost stringing when spaghetti is high (real spaghetti)."""
    result = AnalysisResult(
        stringing_score=0,
        spaghetti_score=95,
        bed_adhesion_failure=True,
        observations="Filamentfäden bilden ein Nest, Teil abgelöst",
        confidence=1.0,
        reasoning="Spaghetti",
    )
    corrected = mistral.apply_plausibility_rules(result)
    # Should not boost stringing because spaghetti >= 50
    assert corrected.stringing_score < 40


def test_check_plausibility_applies_rules():
    """check_plausibility should apply plausibility rules after keyword check."""
    result = AnalysisResult(
        stringing_score=85,
        spaghetti_score=90,
        bed_adhesion_failure=False,
        observations="Deutliche Fäden zwischen den Türmen",
        confidence=0.8,
    )
    corrected = mistral.check_plausibility(result)
    # Rules should have corrected the spaghetti score
    assert corrected.spaghetti_score < result.spaghetti_score


# -- analyze_with_ensemble ---------------------------------------------------------


async def test_analyze_with_ensemble_high_confidence_clean():
    """High confidence + clean → only quick model called."""
    call_count = 0

    async def post_json(url, *, headers, payload):
        nonlocal call_count
        call_count += 1
        return api_response({
            "stringing_score": 5,
            "spaghetti_score": 0,
            "bed_adhesion_failure": False,
            "observations": "Sauberer Druck, keine Auffälligkeiten.",
            "warping_score": 0,
            "layer_shift_score": 0,
            "confidence": 0.95,
            "reasoning": "Sauberer Druck ohne Defekte",
        })

    # Without plausibility rules (default): raw scores preserved
    result = await mistral.analyze_with_ensemble(
        post_json, api_key="k", frame=b"x"
    )
    assert call_count == 1  # Only quick model
    assert result.stringing_score == 5  # Raw score, no rules applied

    # With plausibility rules: Rule 4 sets scores to 0 for "Sauberer Druck"
    call_count = 0
    result = await mistral.analyze_with_ensemble(
        post_json, api_key="k", frame=b"x", plausibility_rules_enabled=True
    )
    assert call_count == 1  # Only quick model
    assert result.stringing_score == 0  # Rule 4 applied


async def test_analyze_with_ensemble_low_confidence_calls_detailed():
    """Low confidence → detailed model also called."""
    call_count = 0

    async def post_json(url, *, headers, payload):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            # Quick model: low confidence, borderline score
            return api_response({
                "stringing_score": 50,
                "spaghetti_score": 0,
                "bed_adhesion_failure": False,
                "observations": "Möglicherweise leichte Fäden zwischen Strukturen.",
                "warping_score": 0,
                "layer_shift_score": 0,
                "confidence": 0.5,
                "reasoning": "Unsicher",
            })
        else:
            # Detailed model: high confidence
            return api_response({
                "stringing_score": 70,
                "spaghetti_score": 0,
                "bed_adhesion_failure": False,
                "observations": "Deutliche Fäden zwischen den Türmen sichtbar.",
                "warping_score": 0,
                "layer_shift_score": 0,
                "confidence": 0.9,
                "reasoning": "Deutliches Stringing erkannt",
            })

    result = await mistral.analyze_with_ensemble(
        post_json, api_key="k", frame=b"x"
    )
    assert call_count == 2  # Both models called
    assert result.stringing_score == 70  # Higher score wins for defects
    assert result.confidence == 0.9


# -- analyze_with_critical_ensemble (v3.1) ----------------------------------------


async def test_critical_ensemble_critical_defect_always_calls_both():
    """Bei kritischem Defekt (Spaghetti/Layer-Shift) IMMER beide Modelle."""
    call_count = 0

    async def post_json(url, *, headers, payload):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            # Quick model: Spaghetti erkannt
            return api_response({
                "stringing_score": 0,
                "spaghetti_score": 85,
                "warping_score": 0,
                "layer_shift_score": 0,
                "bed_adhesion_failure": True,
                "confidence": 0.95,
                "reasoning": "Materialnest erkannt",
                "observations": "Komplettes Spaghetti-Nest",
            })
        else:
            # Detailed model: auch Spaghetti
            return api_response({
                "stringing_score": 0,
                "spaghetti_score": 90,
                "warping_score": 0,
                "layer_shift_score": 0,
                "bed_adhesion_failure": True,
                "confidence": 0.98,
                "reasoning": "Spaghetti bestätigt",
                "observations": "Extremes Materialnest",
            })

    result = await mistral.analyze_with_critical_ensemble(
        post_json, api_key="k", frame=b"x"
    )
    assert call_count == 2  # Beide Modelle bei kritischem Defekt
    assert result.spaghetti_score == 90  # Maximum gewinnt
    assert "Ensemble" in result.reasoning


async def test_critical_ensemble_clean_high_confidence_single_call():
    """Bei Clean mit hoher Konfidenz nur ein Modell."""
    call_count = 0

    async def post_json(url, *, headers, payload):
        nonlocal call_count
        call_count += 1
        return api_response({
            "stringing_score": 0,
            "spaghetti_score": 0,
            "warping_score": 0,
            "layer_shift_score": 0,
            "bed_adhesion_failure": False,
            "confidence": 0.95,
            "reasoning": "Sauberer Druck",
            "observations": "Keine Defekte",
        })

    result = await mistral.analyze_with_critical_ensemble(
        post_json, api_key="k", frame=b"x"
    )
    assert call_count == 1  # Nur ein Modell bei sicherem Clean
    assert result.stringing_score == 0


async def test_critical_ensemble_disagreement_uses_maximum():
    """Bei disagreement auf kritischen Defekten: Maximum (konservativ)."""
    call_count = 0

    async def post_json(url, *, headers, payload):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            # Quick: Layer Shift erkannt
            return api_response({
                "stringing_score": 0,
                "spaghetti_score": 0,
                "warping_score": 0,
                "layer_shift_score": 75,
                "bed_adhesion_failure": False,
                "confidence": 0.8,
                "reasoning": "Layer Shift sichtbar",
                "observations": "Stufenartige Struktur",
            })
        else:
            # Detailed: Niedrigerer Layer Shift
            return api_response({
                "stringing_score": 0,
                "spaghetti_score": 0,
                "warping_score": 0,
                "layer_shift_score": 60,
                "bed_adhesion_failure": False,
                "confidence": 0.9,
                "reasoning": "Leichte Verschiebung",
                "observations": "Minimale Stufen",
            })

    result = await mistral.analyze_with_critical_ensemble(
        post_json, api_key="k", frame=b"x"
    )
    assert call_count == 2
    assert result.layer_shift_score == 75  # Maximum von beiden
