"""Mistral Vision API client for print defect classification.

Home Assistant free: HTTP access is injected as an async ``post_json``
callable so tests can run without aiohttp or network access.
"""
from __future__ import annotations

import base64
import binascii
import json
import re
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from . import prompt as prompt_mod

MISTRAL_CHAT_URL = "https://api.mistral.ai/v1/chat/completions"

KIND_API = "api"
KIND_PARSE = "parse"
KIND_PLAUSIBILITY = "plausibility"

# Keywords that contradict an "all clean" answer (section 4.3: observations
# must match the scores; inconsistent answers are discarded).
_DEFECT_KEYWORDS = (
    "spaghetti",
    "fäden",
    "faden",
    "spinnweb",
    "klumpen",
    "abgelöst",
    "nest",
    "stringing",
    "warping",
    "verzug",
    "abgehoben",
    "schüssel",
    "versetzt",
    "versatz",
    "layer shift",
    "layer-shift",
    "unterextrusion",
    "blob",
    "scarring",
)


class AnalysisError(Exception):
    """Raised when a frame could not be analysed or the answer is invalid.

    ``kind`` is one of ``api`` (transport/HTTP error), ``parse`` (invalid
    JSON/schema) or ``plausibility`` (inconsistent answer).
    """

    def __init__(self, kind: str, message: str) -> None:
        super().__init__(message)
        self.kind = kind


@dataclass(frozen=True)
class AnalysisResult:
    stringing_score: int
    spaghetti_score: int
    bed_adhesion_failure: bool
    observations: str
    warping_score: int = 0
    layer_shift_score: int = 0
    other_defects: tuple[str, ...] = ()


@dataclass(frozen=True)
class MistralRequest:
    url: str
    headers: dict[str, str]
    payload: dict[str, Any]


def build_request(
    *,
    api_key: str,
    model: str,
    image_b64: str,
    context: str = "",
    temperature: float = 0.0,
) -> MistralRequest:
    """Build the chat completions request for one chamber frame."""
    payload = {
        "model": model,
        "temperature": temperature,
        # Required for greedy sampling (temperature=0) on reasoning models
        # such as mistral-large-4, otherwise the API rejects with HTTP 400.
        "top_p": 1,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": prompt_mod.SYSTEM_PROMPT},
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": prompt_mod.build_user_text(context),
                    },
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/jpeg;base64,{image_b64}"
                        },
                    },
                ],
            },
        ],
    }
    return MistralRequest(
        url=MISTRAL_CHAT_URL,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        payload=payload,
    )


def encode_image(frame: bytes) -> str:
    """Base64-encode a JPEG frame."""
    try:
        return base64.b64encode(frame).decode("ascii")
    except (TypeError, binascii.Error) as err:
        raise AnalysisError(KIND_PARSE, f"cannot encode frame: {err}") from err


def _extract_content(data: Any) -> str:
    if not isinstance(data, dict):
        raise AnalysisError(KIND_PARSE, "response is not an object")
    choices = data.get("choices")
    if not isinstance(choices, list) or not choices:
        raise AnalysisError(KIND_PARSE, "response has no choices")
    message = choices[0].get("message") if isinstance(choices[0], dict) else None
    if not isinstance(message, dict):
        raise AnalysisError(KIND_PARSE, "response has no message")
    content = message.get("content")
    if isinstance(content, list):
        # Some providers return a list of content parts.
        content = " ".join(
            part.get("text", "")
            for part in content
            if isinstance(part, dict) and "text" in part
        )
    if not isinstance(content, str) or not content.strip():
        raise AnalysisError(KIND_PARSE, "message content is empty")
    return content


def _coerce_score(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise AnalysisError(KIND_PARSE, f"score is not numeric: {value!r}")
    score = int(round(float(value)))
    if not 0 <= score <= 100:
        raise AnalysisError(KIND_PARSE, f"score out of range 0-100: {score}")
    return score


def _coerce_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value in (0, 1):
        return bool(value)
    raise AnalysisError(KIND_PARSE, f"bed_adhesion_failure is not boolean: {value!r}")


_MAX_OTHER_DEFECTS = 3
_MAX_DEFECT_LEN = 80


def _coerce_other_defects(value: Any) -> tuple[str, ...]:
    """Coerce the optional ``other_defects`` field (robust to model drift).

    Missing/null -> empty tuple. A single string is wrapped into a list.
    Entries are stripped, empties dropped, at most 3 kept and truncated.
    """
    if value is None:
        return ()
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list):
        raise AnalysisError(KIND_PARSE, f"other_defects is not a list: {value!r}")
    cleaned: list[str] = []
    for item in value[:_MAX_OTHER_DEFECTS]:
        text = str(item).strip()
        if text:
            cleaned.append(text[:_MAX_DEFECT_LEN])
    return tuple(cleaned)


def parse_response(data: Any) -> AnalysisResult:
    """Parse and schema-validate a chat completions response."""
    content = _extract_content(data)
    try:
        parsed = json.loads(content)
    except (json.JSONDecodeError, TypeError):
        # Fallback: model wrapped the JSON in prose or markdown fences.
        try:
            parsed = json.loads(extract_json_block(content))
        except (json.JSONDecodeError, TypeError) as err:
            raise AnalysisError(
                KIND_PARSE, f"message content is not valid JSON: {err}"
            ) from err
    if not isinstance(parsed, dict):
        raise AnalysisError(KIND_PARSE, "JSON content is not an object")
    missing = [
        key
        for key in ("stringing_score", "spaghetti_score", "bed_adhesion_failure",
                    "observations")
        if key not in parsed
    ]
    if missing:
        raise AnalysisError(KIND_PARSE, f"missing keys: {', '.join(missing)}")
    observations = parsed["observations"]
    if not isinstance(observations, str) or not observations.strip():
        raise AnalysisError(KIND_PARSE, "observations must be a non-empty string")
    # Optional prompt-v2 fields: missing keys default to 0 / () instead of
    # discarding the frame (robust against model/prompt drift).
    warping_score = (
        _coerce_score(parsed["warping_score"])
        if "warping_score" in parsed
        else 0
    )
    layer_shift_score = (
        _coerce_score(parsed["layer_shift_score"])
        if "layer_shift_score" in parsed
        else 0
    )
    return AnalysisResult(
        stringing_score=_coerce_score(parsed["stringing_score"]),
        spaghetti_score=_coerce_score(parsed["spaghetti_score"]),
        bed_adhesion_failure=_coerce_bool(parsed["bed_adhesion_failure"]),
        observations=observations.strip(),
        warping_score=warping_score,
        layer_shift_score=layer_shift_score,
        other_defects=_coerce_other_defects(parsed.get("other_defects")),
    )


def check_plausibility(result: AnalysisResult) -> AnalysisResult:
    """Discard answers whose observations contradict their scores."""
    if result.observations:
        lowered = result.observations.lower()
        has_defect_word = any(word in lowered for word in _DEFECT_KEYWORDS)
        if (
            has_defect_word
            and result.stringing_score <= 15
            and result.spaghetti_score <= 15
            and result.warping_score <= 15
            and result.layer_shift_score <= 15
        ):
            raise AnalysisError(
                KIND_PLAUSIBILITY,
                "observations mention defects while scores are near zero",
            )
    return result


async def analyze_frame(
    post_json: Callable[..., Awaitable[Any]],
    *,
    api_key: str,
    model: str,
    frame: bytes,
    context: str = "",
) -> AnalysisResult:
    """Grab an analysis for one JPEG frame via the injected HTTP callable.

    ``post_json`` is called as ``await post_json(url, headers=..., payload=...)``
    and must raise on transport/HTTP errors. Those are wrapped into
    ``AnalysisError(kind="api")``.
    """
    request = build_request(
        api_key=api_key, model=model, image_b64=encode_image(frame), context=context
    )
    try:
        data = await post_json(
            request.url, headers=request.headers, payload=request.payload
        )
    except AnalysisError:
        raise
    except Exception as err:  # noqa: BLE001 - transport errors must not leak
        raise AnalysisError(KIND_API, f"Mistral API call failed: {err}") from err
    result = parse_response(data)
    return check_plausibility(result)


def extract_json_block(text: str) -> str:
    """Extract a JSON object from a text that may embed markdown fences.

    Used as a fallback when the API ignores the JSON response format.
    """
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        return match.group(0)
    return text
