"""Decision logic: thresholds, streak, cooldown, once-per-print (section 3.2).

Home Assistant free. Invalid frames never reach ``process()``; the runtime
discards them separately (spec 4.3: parse error => frame discarded, not
counted as failure and neither advancing nor resetting streaks).
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Callable

from .mistral import AnalysisResult


@dataclass(frozen=True)
class EngineConfig:
    """Section 6 parameters relevant for the decision engine."""

    stringing_threshold: int = 55
    stringing_streak: int = 3
    spaghetti_threshold: int = 70
    stringing_cooldown_sec: int = 15 * 60
    warping_threshold: int = 60
    layer_shift_threshold: int = 70
    # Prompt v3.0: confidence-based filtering and EMA smoothing
    min_confidence: float = 0.6
    smoothing_enabled: bool = True
    smoothing_alpha: float = 0.3


@dataclass
class Decision:
    """Outcome of processing one frame."""

    stringing_event: bool = False
    spaghetti_event: bool = False
    warping_event: bool = False
    layer_shift_event: bool = False
    stringing_detected: bool = False
    warping_detected: bool = False
    layer_shift_detected: bool = False
    print_failure: bool = False
    muted: bool = False
    discarded: bool = False


@dataclass
class EngineStats:
    """Counters exposed to Home Assistant entities."""

    stringing_events: int = 0
    spaghetti_events: int = 0
    warping_events: int = 0
    layer_shift_events: int = 0
    discarded_frames: int = 0
    low_confidence_frames: int = 0


@dataclass
class DecisionEngine:
    """Stateful per-printer decision engine (one instance per printer)."""

    config: EngineConfig
    time_fn: Callable[[], float] = field(default=time.monotonic, repr=False)

    def __post_init__(self) -> None:
        # Stringing-like (streak + hysteresis + cooldown)
        self._streak_above = 0
        self._streak_below = 0
        self._stringing_detected = False
        self._last_stringing_event: float | None = None
        # Warping is handled stringing-like with its own streaks/cooldown
        self._warping_above = 0
        self._warping_below = 0
        self._warping_detected = False
        self._last_warping_event: float | None = None
        # Spaghetti-like (immediate, once per print, auto-recovery)
        self._print_failure = False
        self._spaghetti_fired = False
        self._spaghetti_below_streak = 0
        # Layer shift is handled spaghetti-like
        self._layer_shift_detected = False
        self._layer_shift_fired = False
        self._layer_shift_below_streak = 0
        self._muted = False
        self.stats = EngineStats()
        # EMA smoothing state (Prompt v3.0)
        self._last_smoothed: AnalysisResult | None = None
        self._frame_count: int = 0

    # -- lifecycle -----------------------------------------------------------

    def start_print(self) -> None:
        """Reset all per-print state (called when a new print begins)."""
        self.reset()
        self._muted = False

    def reset(self) -> None:
        """Clear streaks, detection flags, notification latches and cooldowns.

        The mute switch is deliberately untouched (it is a separate user
        decision), as is the print id which lives in the runtime.
        """
        self._streak_above = 0
        self._streak_below = 0
        self._stringing_detected = False
        self._last_stringing_event = None
        self._warping_above = 0
        self._warping_below = 0
        self._warping_detected = False
        self._last_warping_event = None
        self._print_failure = False
        self._spaghetti_fired = False
        self._spaghetti_below_streak = 0
        self._layer_shift_detected = False
        self._layer_shift_fired = False
        self._layer_shift_below_streak = 0
        # EMA smoothing state zurücksetzen
        self._last_smoothed = None
        self._frame_count = 0

    def mute_current_print(self, muted: bool = True) -> None:
        """Mute (or unmute) notifications and autopause for this print."""
        self._muted = muted

    @property
    def muted(self) -> bool:
        return self._muted

    @property
    def stringing_detected(self) -> bool:
        return self._stringing_detected

    @property
    def warping_detected(self) -> bool:
        return self._warping_detected

    @property
    def layer_shift_detected(self) -> bool:
        return self._layer_shift_detected

    @property
    def print_failure(self) -> bool:
        return self._print_failure

    # -- core ----------------------------------------------------------------

    def _smooth_scores(self, result: AnalysisResult) -> AnalysisResult:
        """Exponential Moving Average über die Scores.

        Reduziert kurzfristige Schwankungen und Ausreißer.
        neu = alpha * aktuell + (1 - alpha) * alt

        WICHTIG: Spaghetti und Layer-Shift werden NICHT geglättet —
        kritische Fehler müssen sofort erkannt werden, ohne Verzögerung
        durch vorherige niedrige Scores.
        """
        if not self.config.smoothing_enabled:
            return result

        self._frame_count += 1

        if self._last_smoothed is None:
            self._last_smoothed = result
            return result

        alpha = self.config.smoothing_alpha
        prev = self._last_smoothed

        smoothed = AnalysisResult(
            stringing_score=int(round(prev.stringing_score * (1 - alpha) + result.stringing_score * alpha)),
            # Spaghetti & Layer-Shift: Rohwerte behalten (keine Glättung für kritische Fehler)
            spaghetti_score=result.spaghetti_score,
            warping_score=int(round(prev.warping_score * (1 - alpha) + result.warping_score * alpha)),
            layer_shift_score=result.layer_shift_score,
            bed_adhesion_failure=result.bed_adhesion_failure,
            observations=result.observations,
            other_defects=result.other_defects,
            confidence=result.confidence,
            reasoning=result.reasoning,
        )

        self._last_smoothed = smoothed
        return smoothed

    def process(self, result: AnalysisResult) -> Decision:
        """Evaluate one valid analysis result and return the decisions."""
        cfg = self.config

        # Konfidenz-Prüfung — Frames mit niedriger Konfidenz verwerfen
        if result.confidence < cfg.min_confidence:
            self.stats.discarded_frames += 1
            self.stats.low_confidence_frames += 1
            return Decision(discarded=True)

        # Scores glätten (EMA)
        smoothed = self._smooth_scores(result)

        stringing_event = self._process_stringing(smoothed)
        warping_event = self._process_warping(smoothed)
        spaghetti_event = self._process_spaghetti(smoothed)
        layer_shift_event = self._process_layer_shift(smoothed)
        return Decision(
            stringing_event=stringing_event,
            spaghetti_event=spaghetti_event,
            warping_event=warping_event,
            layer_shift_event=layer_shift_event,
            stringing_detected=self._stringing_detected,
            warping_detected=self._warping_detected,
            layer_shift_detected=self._layer_shift_detected,
            print_failure=self._print_failure,
            muted=self._muted,
            discarded=False,
        )

    def _process_stringing(self, result: AnalysisResult) -> bool:
        """Streak latch + hysteresis + cooldown, stringing-like."""
        cfg = self.config
        if result.stringing_score >= cfg.stringing_threshold:
            self._streak_above += 1
            self._streak_below = 0
        else:
            self._streak_below += 1
            self._streak_above = 0

        if not self._stringing_detected and self._streak_above >= cfg.stringing_streak:
            self._stringing_detected = True
        elif self._stringing_detected and self._streak_below >= cfg.stringing_streak:
            self._stringing_detected = False

        if not (self._stringing_detected and not self._muted):
            return False
        now = self.time_fn()
        if (
            self._last_stringing_event is None
            or now - self._last_stringing_event >= cfg.stringing_cooldown_sec
        ):
            self._last_stringing_event = now
            self.stats.stringing_events += 1
            return True
        return False

    def _process_warping(self, result: AnalysisResult) -> bool:
        """Warping is handled like stringing: streak, hysteresis, cooldown."""
        cfg = self.config
        if result.warping_score >= cfg.warping_threshold:
            self._warping_above += 1
            self._warping_below = 0
        else:
            self._warping_below += 1
            self._warping_above = 0

        if not self._warping_detected and self._warping_above >= cfg.stringing_streak:
            self._warping_detected = True
        elif self._warping_detected and self._warping_below >= cfg.stringing_streak:
            self._warping_detected = False

        if not (self._warping_detected and not self._muted):
            return False
        now = self.time_fn()
        if (
            self._last_warping_event is None
            or now - self._last_warping_event >= cfg.stringing_cooldown_sec
        ):
            self._last_warping_event = now
            self.stats.warping_events += 1
            return True
        return False

    def _process_spaghetti(self, result: AnalysisResult) -> bool:
        """Immediate, once per print; auto-recovers below the threshold."""
        cfg = self.config
        if result.spaghetti_score >= cfg.spaghetti_threshold:
            self._spaghetti_below_streak = 0
            self._print_failure = True
            if not self._spaghetti_fired and not self._muted:
                self._spaghetti_fired = True
                self.stats.spaghetti_events += 1
                return True
        elif self._print_failure:
            self._spaghetti_below_streak += 1
            if self._spaghetti_below_streak >= cfg.stringing_streak:
                # Auto-recovery: clear the failure and re-arm the notification
                # so a new defect in the same print can alert again.
                self._print_failure = False
                self._spaghetti_below_streak = 0
                self._spaghetti_fired = False
        return False

    def _process_layer_shift(self, result: AnalysisResult) -> bool:
        """Layer shift is handled like spaghetti: immediate, once per print."""
        cfg = self.config
        if result.layer_shift_score >= cfg.layer_shift_threshold:
            self._layer_shift_below_streak = 0
            self._layer_shift_detected = True
            if not self._layer_shift_fired and not self._muted:
                self._layer_shift_fired = True
                self.stats.layer_shift_events += 1
                return True
        elif self._layer_shift_detected:
            self._layer_shift_below_streak += 1
            if self._layer_shift_below_streak >= cfg.stringing_streak:
                self._layer_shift_detected = False
                self._layer_shift_below_streak = 0
                self._layer_shift_fired = False
        return False
