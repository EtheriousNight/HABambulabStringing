"""Mistral Vision API client for print defect classification.

Home Assistant free: HTTP access is injected as an async ``post_json``
callable so tests can run without aiohttp or network access.
"""
from __future__ import annotations

import base64
import binascii
import json
import re
from dataclasses import dataclass, replace
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
    confidence: float = 1.0
    reasoning: str = ""


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


def apply_plausibility_rules(result: AnalysisResult) -> AnalysisResult:
    """Korrigiert offensichtliche Fehlklassifikationen nach der API-Antwort.

    Diese Regeln basieren auf der Beobachtung, dass Modelle dazu neigen:
    - Stringing als Spaghetti zu verwechseln
    - Bei sauberen Drucken trotzdem hohe Scores zu vergeben
    - Mehrere Defekte gleichzeitig zu "erkennen" (Over-Alerting)
    """
    r = result

    # Regel 1: Spaghetti ohne Ablösung + Stringing → wahrscheinlich nur Stringing
    if (r.spaghetti_score > 60
        and not r.bed_adhesion_failure
        and r.stringing_score > 40):
        r = replace(
            r,
            spaghetti_score=min(r.spaghetti_score, 30),
            stringing_score=max(r.stringing_score, 70),
        )

    # Regel 2: Beide hoch (Spaghetti + Stringing) → Entscheidung anhand Ablösung
    if r.spaghetti_score > 70 and r.stringing_score > 70:
        if r.bed_adhesion_failure:
            # Echtes Spaghetti — Stringing ist sekundär
            r = replace(r, stringing_score=min(r.stringing_score, 50))
        else:
            # Kein Spaghetti möglich ohne Ablösung — wahrscheinlich Stringing
            r = replace(
                r,
                spaghetti_score=20,
                stringing_score=max(r.stringing_score, 80),
            )

    # Regel 3: Layer Shift + Stringing gleichzeitig ist unwahrscheinlich
    if r.layer_shift_score > 70 and r.stringing_score > 70:
        obs = r.observations.lower()
        has_stringing_words = any(w in obs for w in ["faden", "fäden", "stringing", "spinnweb", "haar"])
        has_shift_words = any(w in obs for w in ["stufe", "stufen", "versatz", "verschoben", "shift", "terrasse"])

        if has_stringing_words and not has_shift_words:
            r = replace(r, layer_shift_score=min(r.layer_shift_score, 40))
        elif has_shift_words and not has_stringing_words:
            r = replace(r, stringing_score=min(r.stringing_score, 30))

    # Regel 4: Alle Scores sehr niedrig + "sauber" in Observations → sicher clean
    if (r.stringing_score <= 15
        and r.spaghetti_score <= 15
        and r.warping_score <= 15
        and r.layer_shift_score <= 15):
        obs_lower = r.observations.lower()
        clean_words = ["sauber", "fehlerfrei", "keine defekte", "keine mängel", "einwandfrei", "makellos"]
        if any(w in obs_lower for w in clean_words):
            r = replace(
                r,
                stringing_score=0,
                spaghetti_score=0,
                warping_score=0,
                layer_shift_score=0,
            )

    # Regel 5: Spaghetti-Score ohne Ablösung und ohne hohe Stringing → verdächtig
    if r.spaghetti_score > 50 and not r.bed_adhesion_failure and r.stringing_score < 30:
        r = replace(r, spaghetti_score=min(r.spaghetti_score, 30))

    # Regel 6 (v3.2): Spaghetti trotz "stehender Teile" in Observations →
    # Fehlklassifikation. Modelle verwechseln dichtes Stringing zwischen
    # stehenden Türmen/Säulen mit Spaghetti (Benchmark: stringing_2.jpg).
    # WICHTIG: Nur Observations prüfen, nicht Reasoning (das ist die
    # fehlerhafte Schlussfolgerung des Modells!).
    # SEHR KONSERVATIV: Nur bei extrem hohem Spaghetti-Score (>80) und
    # eindeutigen stehenden Strukturen ohne JEGLICHE Nest-Indikatoren.
    if r.spaghetti_score > 80 and r.stringing_score < 20:
        obs_lower = r.observations.lower()
        # Starke Indikatoren für stehende, intakte Strukturen
        strong_standing_keywords = [
            "steht fest", "stehen fest", "steht stabil", "stehen stabil",
            "turm", "türme", "säule", "säulen", "zylinder",
            "grundplatte", "intakt", "aufrecht",
        ]
        # ALLE Nest-Indikatoren (auch schwache) — bei deren Vorhandensein NICHT korrigieren
        any_nest_keywords = [
            "nest", "knäuel", "chaos", "chaotisch", "wirr", "verheddert",
            "abgelöst", "losgelöst", "gelöst", "klumpen", "knäuel",
            "kein stehendes teil", "keine erkennbare struktur",
            "nichts erkennbar", "nur noch nest", "nur nest",
            "komplett abgelöst", "vollständig abgelöst", "entartet",
            "materialnest", "filamentnest", "filamentknäuel",
        ]
        # Zähle starke stehende Indikatoren (mindestens 2 erforderlich)
        standing_count = sum(1 for kw in strong_standing_keywords if kw in obs_lower)
        has_any_nest = any(kw in obs_lower for kw in any_nest_keywords)

        # Nur korrigieren wenn: mind. 2 starke stehende Indikatoren UND keine Nest-Indikatoren
        if standing_count >= 2 and not has_any_nest:
            r = replace(
                r,
                spaghetti_score=min(r.spaghetti_score, 25),
                stringing_score=max(r.stringing_score, 75),
                bed_adhesion_failure=False,
            )

    # Regel 7 (v3.2): Stringing-Score 0 bei erkannten Fäden in Observations →
    # Modelle übersehen manchmal Stringing komplett (Benchmark: stringing_1, _5).
    # Auch hier nur Observations prüfen (Reasoning ist die fehlerhafte Conclusion).
    # KRITISCH: Negationen wie "keine Fäden" dürfen NICHT triggern!
    if r.stringing_score < 10:
        obs_lower = r.observations.lower()
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
        # Nur wenn wirklich Fäden beschrieben werden (ohne Negation!) und Score 0
        if has_stringing_words and not has_negation and r.spaghetti_score < 50:
            r = replace(r, stringing_score=max(r.stringing_score, 40))

    return r


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
    # Prompt v3.0: confidence and reasoning (optional with defaults)
    confidence = parsed.get("confidence", 1.0)
    if not isinstance(confidence, (int, float)) or isinstance(confidence, bool):
        confidence = 1.0
    confidence = max(0.0, min(1.0, float(confidence)))

    reasoning = str(parsed.get("reasoning", "")).strip()[:200]

    return AnalysisResult(
        stringing_score=_coerce_score(parsed["stringing_score"]),
        spaghetti_score=_coerce_score(parsed["spaghetti_score"]),
        bed_adhesion_failure=_coerce_bool(parsed["bed_adhesion_failure"]),
        observations=observations.strip(),
        warping_score=warping_score,
        layer_shift_score=layer_shift_score,
        other_defects=_coerce_other_defects(parsed.get("other_defects")),
        confidence=confidence,
        reasoning=reasoning,
    )


def check_plausibility(result: AnalysisResult, *, apply_rules: bool = True) -> AnalysisResult:
    """Discard answers whose observations contradict their scores.

    Args:
        result: The analysis result to check.
        apply_rules: If True, apply plausibility rules (v3.2) to correct
            obvious misclassifications. If False, only the sanity check
            (observations vs scores contradiction) is performed.
            Default: True (backwards compatible).
            NOTE: Benchmark shows rules can DEGRADE accuracy (glm: 77.9% → 64.3%),
            so the integration defaults to False.
    """
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
    # Regelbasierte Korrektur nur wenn aktiviert (kann Accuracy verschlechtern!)
    if apply_rules:
        return apply_plausibility_rules(result)
    return result


async def analyze_frame(
    post_json: Callable[..., Awaitable[Any]],
    *,
    api_key: str,
    model: str,
    frame: bytes,
    context: str = "",
    plausibility_rules_enabled: bool = False,
) -> AnalysisResult:
    """Grab an analysis for one JPEG frame via the injected HTTP callable.

    ``post_json`` is called as ``await post_json(url, headers=..., payload=...)``
    and must raise on transport/HTTP errors. Those are wrapped into
    ``AnalysisError(kind="api")``.

    Args:
        plausibility_rules_enabled: If True, apply plausibility rules (v3.2).
            Default: False (rules can degrade accuracy, see benchmark).
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
    return check_plausibility(result, apply_rules=plausibility_rules_enabled)


def extract_json_block(text: str) -> str:
    """Extract a JSON object from a text that may embed markdown fences.

    Used as a fallback when the API ignores the JSON response format.
    """
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        return match.group(0)
    return text


async def analyze_with_ensemble(
    post_json: Callable[..., Awaitable[Any]],
    *,
    api_key: str,
    frame: bytes,
    context: str = "",
    quick_model: str = "mistral-small-latest",
    detailed_model: str = "mistral-medium-latest",
    confidence_threshold: float = 0.7,
    defect_threshold: int = 40,
    plausibility_rules_enabled: bool = False,
) -> AnalysisResult:
    """Zweistufige Analyse: Schnelles Modell zuerst, bei Unsicherheit genaueres.

    Spart Kosten bei eindeutigen Fällen (clean oder offensichtlich defekt),
    erhöht Genauigkeit bei grenzwertigen Fällen.
    """
    # Stufe 1: Schnelles, günstiges Modell
    quick = await analyze_frame(
        post_json, api_key=api_key, model=quick_model, frame=frame, context=context,
        plausibility_rules_enabled=plausibility_rules_enabled,
    )

    max_score = max(
        quick.stringing_score,
        quick.spaghetti_score,
        quick.warping_score,
        quick.layer_shift_score,
    )

    # Bei hoher Konfidenz UND (clean ODER eindeutig defekt) → fertig
    if quick.confidence >= confidence_threshold and (
        max_score < defect_threshold or max_score > 80
    ):
        return quick

    # Stufe 2: Genaueres Modell bei Unsicherheit oder grenzwertigem Defekt
    detailed = await analyze_frame(
        post_json, api_key=api_key, model=detailed_model, frame=frame, context=context,
        plausibility_rules_enabled=plausibility_rules_enabled,
    )

    # Kombiniere Ergebnisse:
    # - Bei erkanntem Defekt: Nimm den höheren Score (konservativ)
    # - Bei Clean: Nimm den niedrigeren Score (keine False Positives)
    if max_score >= defect_threshold:
        return AnalysisResult(
            stringing_score=max(quick.stringing_score, detailed.stringing_score),
            spaghetti_score=max(quick.spaghetti_score, detailed.spaghetti_score),
            warping_score=max(quick.warping_score, detailed.warping_score),
            layer_shift_score=max(quick.layer_shift_score, detailed.layer_shift_score),
            bed_adhesion_failure=quick.bed_adhesion_failure or detailed.bed_adhesion_failure,
            observations=detailed.observations,
            other_defects=detailed.other_defects,
            confidence=max(quick.confidence, detailed.confidence),
            reasoning=detailed.reasoning,
        )
    else:
        return AnalysisResult(
            stringing_score=min(quick.stringing_score, detailed.stringing_score),
            spaghetti_score=min(quick.spaghetti_score, detailed.spaghetti_score),
            warping_score=min(quick.warping_score, detailed.warping_score),
            layer_shift_score=min(quick.layer_shift_score, detailed.layer_shift_score),
            bed_adhesion_failure=quick.bed_adhesion_failure and detailed.bed_adhesion_failure,
            observations=detailed.observations,
            other_defects=detailed.other_defects,
            confidence=max(quick.confidence, detailed.confidence),
            reasoning=detailed.reasoning,
        )


async def analyze_with_critical_ensemble(
    post_json: Callable[..., Awaitable[Any]],
    *,
    api_key: str,
    frame: bytes,
    context: str = "",
    # Benchmark-optimierte Modelle (v3.1):
    # glm-5-3-flash: günstig (0.08¢/Scan), 100% Stringing/Spaghetti
    # mistral-medium-latest: schnell (1.7s), 86.4% accuracy, beste Production Score
    quick_model: str = "zai-glm-5-3-flash",
    detailed_model: str = "mistral-medium-latest",
    confidence_threshold: float = 0.7,
    non_critical_threshold: int = 40,
    critical_threshold: int = 50,
    plausibility_rules_enabled: bool = False,
) -> AnalysisResult:
    """Kritisches Ensemble für Produktionsumgebung (Benchmark-optimiert).

    Strategie:
    - Stufe 1: glm-5-3-flash (günstig, 100% Stringing/Spaghetti)
    - Stufe 2: mistral-medium-latest (schnell, 86.4% Acc, 1.7s Latenz)

    Besonderheiten:
    - KRITISCHE Defekte (Spaghetti, Layer-Shift): IMMER beide Modelle,
      Maximum-Score gewinnt (konservativ, keine False Negatives!)
    - Nicht-kritische Defekte (Stringing, Warping): Nur bei Unsicherheit
      zweites Modell, sonst nur Stufe 1 (spart Kosten)
    - Clean: Nur Stufe 1 bei hoher Konfidenz, sonst Stufe 2 zur Sicherheit

    Basierend auf Benchmark v3.4: Beste Balance aus Kosten und Genauigkeit
    für kritische Fehlerfälle.
    """
    # Stufe 1: Günstiges Modell (glm-5-3-flash)
    quick = await analyze_frame(
        post_json, api_key=api_key, model=quick_model, frame=frame, context=context,
        plausibility_rules_enabled=plausibility_rules_enabled,
    )

    # Kritische Scores vom ersten Modell
    critical_detected = (
        quick.spaghetti_score >= critical_threshold
        or quick.layer_shift_score >= critical_threshold
    )
    
    non_critical_score = max(
        quick.stringing_score,
        quick.warping_score,
    )
    
    max_quick = max(
        quick.stringing_score,
        quick.spaghetti_score,
        quick.warping_score,
        quick.layer_shift_score,
    )

    # Entscheidung: Zweites Modell nötig?
    need_second_model = False
    reason = ""
    
    if critical_detected:
        # KRITISCH: Immer zweites Modell zur Bestätigung!
        need_second_model = True
        reason = "critical defect detected"
    elif quick.confidence < confidence_threshold:
        # Unsichere Antwort → zweites Modell
        need_second_model = True
        reason = "low confidence"
    elif non_critical_score >= non_critical_threshold and max_quick < 80:
        # Grenzwertiger nicht-kritischer Defekt → zweites Modell
        need_second_model = True
        reason = "borderline non-critical"
    elif max_quick < 20 and quick.confidence < 0.85:
        # Mögliches Clean, aber nicht sicher → zweites Modell
        need_second_model = True
        reason = "uncertain clean"
    
    if not need_second_model:
        # Nur Stufe 1 nötig
        return quick

    # Stufe 2: Zuverlässiges Modell (mistral-medium-latest)
    detailed = await analyze_frame(
        post_json, api_key=api_key, model=detailed_model, frame=frame, context=context,
        plausibility_rules_enabled=plausibility_rules_enabled,
    )

    # Kombiniere Ergebnisse mit kritischem Fokus
    if critical_detected or detailed.spaghetti_score >= critical_threshold or detailed.layer_shift_score >= critical_threshold:
        # KRITISCHER Fall: Maximum-Score für kritische Defekte (konservativ!)
        # Nicht-kritische: Durchschnitt (ausgewogener)
        return AnalysisResult(
            stringing_score=int((quick.stringing_score + detailed.stringing_score) / 2),
            spaghetti_score=max(quick.spaghetti_score, detailed.spaghetti_score),
            warping_score=int((quick.warping_score + detailed.warping_score) / 2),
            layer_shift_score=max(quick.layer_shift_score, detailed.layer_shift_score),
            bed_adhesion_failure=(
                quick.bed_adhesion_failure or detailed.bed_adhesion_failure
            ),
            observations=detailed.observations or quick.observations,
            other_defects=detailed.other_defects or quick.other_defects,
            confidence=max(quick.confidence, detailed.confidence),
            reasoning=f"[Ensemble: {reason}] {detailed.reasoning or quick.reasoning}",
        )
    elif max_quick >= non_critical_threshold:
        # Nicht-kritischer Defekt: Maximum für Sicherheit
        return AnalysisResult(
            stringing_score=max(quick.stringing_score, detailed.stringing_score),
            spaghetti_score=max(quick.spaghetti_score, detailed.spaghetti_score),
            warping_score=max(quick.warping_score, detailed.warping_score),
            layer_shift_score=max(quick.layer_shift_score, detailed.layer_shift_score),
            bed_adhesion_failure=(
                quick.bed_adhesion_failure or detailed.bed_adhesion_failure
            ),
            observations=detailed.observations or quick.observations,
            other_defects=detailed.other_defects or quick.other_defects,
            confidence=max(quick.confidence, detailed.confidence),
            reasoning=f"[Ensemble: {reason}] {detailed.reasoning or quick.reasoning}",
        )
    else:
        # Clean oder unsicher: Minimum für konservatives Clean
        return AnalysisResult(
            stringing_score=min(quick.stringing_score, detailed.stringing_score),
            spaghetti_score=min(quick.spaghetti_score, detailed.spaghetti_score),
            warping_score=min(quick.warping_score, detailed.warping_score),
            layer_shift_score=min(quick.layer_shift_score, detailed.layer_shift_score),
            bed_adhesion_failure=(
                quick.bed_adhesion_failure and detailed.bed_adhesion_failure
            ),
            observations=detailed.observations or quick.observations,
            other_defects=detailed.other_defects or quick.other_defects,
            confidence=max(quick.confidence, detailed.confidence),
            reasoning=f"[Ensemble: {reason}] {detailed.reasoning or quick.reasoning}",
        )
