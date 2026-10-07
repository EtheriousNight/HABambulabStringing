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
    result = AnalysisResult(5, 0, False, "Sauberer Druck, keine Auffälligkeiten.")
    assert mistral.check_plausibility(result) is result
    flagged = AnalysisResult(60, 10, False, "Viele Fäden zwischen den Türmen.")
    assert mistral.check_plausibility(flagged) is flagged


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
    assert mistral.check_plausibility(result) is result
    shifted = AnalysisResult(
        0, 0, False, "Layer deutlich versetzt.", layer_shift_score=80
    )
    assert mistral.check_plausibility(shifted) is shifted


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
