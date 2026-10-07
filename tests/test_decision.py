"""Tests for the decision engine (streak, cooldown, once-per-print, mute)."""
from __future__ import annotations

import pytest

from conftest import CORE
from bs_core.decision import DecisionEngine, EngineConfig
from bs_core.mistral import AnalysisResult


def result(stringing=0, spaghetti=0, observations="Sauberer Druck.",
           warping=0, layer_shift=0):
    return AnalysisResult(
        stringing_score=stringing,
        spaghetti_score=spaghetti,
        bed_adhesion_failure=False,
        observations=observations,
        warping_score=warping,
        layer_shift_score=layer_shift,
    )


class FakeClock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


@pytest.fixture()
def clock():
    return FakeClock()


@pytest.fixture()
def engine(clock):
    return DecisionEngine(
        EngineConfig(
            stringing_threshold=55,
            stringing_streak=3,
            spaghetti_threshold=70,
            stringing_cooldown_sec=900,
            warping_threshold=60,
            layer_shift_threshold=70,
        ),
        time_fn=clock,
    )


def test_below_threshold_never_detects(engine):
    for _ in range(10):
        d = engine.process(result(stringing=30))
        assert not d.stringing_detected
        assert not d.stringing_event


def test_streak_required_before_event(engine, clock):
    d = engine.process(result(stringing=60))
    assert not d.stringing_detected and not d.stringing_event
    d = engine.process(result(stringing=60))
    assert not d.stringing_detected and not d.stringing_event
    d = engine.process(result(stringing=60))
    assert d.stringing_detected and d.stringing_event
    assert engine.stats.stringing_events == 1


def test_threshold_is_inclusive(engine):
    for _ in range(3):
        d = engine.process(result(stringing=55))
    assert d.stringing_detected


def test_streak_resets_below_threshold(engine):
    engine.process(result(stringing=60))
    engine.process(result(stringing=60))
    engine.process(result(stringing=10))  # reset
    d = engine.process(result(stringing=60))
    assert not d.stringing_detected


def test_cooldown_limits_stringing_notifications(engine, clock):
    for _ in range(3):
        d = engine.process(result(stringing=60))
    assert d.stringing_event
    clock.advance(60)
    d = engine.process(result(stringing=60))
    assert d.stringing_detected and not d.stringing_event
    clock.advance(900)
    d = engine.process(result(stringing=60))
    assert d.stringing_event
    assert engine.stats.stringing_events == 2


def test_detected_latches_and_clears_with_hysteresis(engine):
    for _ in range(3):
        engine.process(result(stringing=60))
    d = engine.process(result(stringing=10))
    assert d.stringing_detected  # latched, below-streak only 1
    d = engine.process(result(stringing=10))
    assert d.stringing_detected  # below-streak 2
    d = engine.process(result(stringing=10))
    assert not d.stringing_detected  # below-streak 3 -> cleared
    # after clearing, a single below frame must not re-trigger
    assert not d.stringing_event


def test_spaghetti_immediate_once_per_print(engine, clock):
    d = engine.process(result(spaghetti=75))
    assert d.print_failure and d.spaghetti_event
    clock.advance(10)
    d = engine.process(result(spaghetti=90))
    assert d.print_failure and not d.spaghetti_event  # only once per print
    assert engine.stats.spaghetti_events == 1


def test_spaghetti_resets_on_new_print(engine):
    engine.process(result(spaghetti=75))
    assert engine.print_failure
    engine.start_print()
    assert not engine.print_failure and not engine.muted
    d = engine.process(result(spaghetti=75))
    assert d.spaghetti_event  # fires again in the new print
    assert engine.stats.spaghetti_events == 2


def test_mute_suppresses_events_but_not_detection(engine):
    engine.mute_current_print()
    for _ in range(3):
        d = engine.process(result(stringing=60, spaghetti=75))
    assert d.stringing_detected and d.print_failure
    assert not d.stringing_event and not d.spaghetti_event
    assert engine.muted
    # unmute re-enables notifications
    engine.mute_current_print(False)
    d = engine.process(result(spaghetti=75))
    assert d.spaghetti_event  # spaghetti never fired for this print yet


def test_mute_resets_with_new_print(engine):
    engine.mute_current_print()
    engine.start_print()
    assert not engine.muted


def test_stringing_event_not_counted_as_spaghetti(engine):
    d = engine.process(result(stringing=70, spaghetti=20))
    assert not d.print_failure and not d.spaghetti_event
    assert not d.stringing_event  # streak of 1


# -- auto recovery of print_failure --------------------------------------------


def test_print_failure_auto_recovers_below_streak(engine):
    engine.process(result(spaghetti=75))
    assert engine.print_failure
    engine.process(result(spaghetti=10))
    engine.process(result(spaghetti=10))
    d = engine.process(result(spaghetti=10))
    assert not d.print_failure
    # re-armed: a new defect in the same print alerts again
    d = engine.process(result(spaghetti=80))
    assert d.print_failure and d.spaghetti_event
    assert engine.stats.spaghetti_events == 2


def test_print_failure_recovery_requires_consecutive_below(engine):
    engine.process(result(spaghetti=75))
    engine.process(result(spaghetti=10))
    engine.process(result(spaghetti=10))
    engine.process(result(spaghetti=90))  # above again -> streak reset
    d = engine.process(result(spaghetti=10))
    assert d.print_failure  # only 1 below since the spike


# -- warping (stringing-like) ----------------------------------------------------


def test_warping_streak_and_hysteresis(engine, clock):
    d = engine.process(result(warping=65))
    assert not d.warping_detected and not d.warping_event
    engine.process(result(warping=65))
    d = engine.process(result(warping=65))
    assert d.warping_detected and d.warping_event
    assert engine.stats.warping_events == 1
    # latched below
    engine.process(result(warping=10))
    d = engine.process(result(warping=10))
    assert d.warping_detected
    d = engine.process(result(warping=10))
    assert not d.warping_detected


def test_warping_cooldown(engine, clock):
    for _ in range(3):
        d = engine.process(result(warping=65))
    assert d.warping_event
    clock.advance(60)
    d = engine.process(result(warping=65))
    assert d.warping_detected and not d.warping_event
    clock.advance(900)
    d = engine.process(result(warping=65))
    assert d.warping_event
    assert engine.stats.warping_events == 2


def test_warping_independent_from_stringing(engine):
    for _ in range(4):
        d = engine.process(result(stringing=60, warping=10))
    assert d.stringing_detected and not d.warping_detected
    for _ in range(4):
        d = engine.process(result(warping=65))
    assert d.warping_detected


# -- layer shift (spaghetti-like) -------------------------------------------------


def test_layer_shift_immediate_once_per_print(engine):
    d = engine.process(result(layer_shift=75))
    assert d.layer_shift_detected and d.layer_shift_event
    d = engine.process(result(layer_shift=90))
    assert d.layer_shift_detected and not d.layer_shift_event
    assert engine.stats.layer_shift_events == 1


def test_layer_shift_auto_recovers_and_re_fires(engine):
    engine.process(result(layer_shift=75))
    assert engine.layer_shift_detected
    for _ in range(3):
        d = engine.process(result(layer_shift=10))
    assert not d.layer_shift_detected
    d = engine.process(result(layer_shift=80))
    assert d.layer_shift_detected and d.layer_shift_event
    assert engine.stats.layer_shift_events == 2


def test_layer_shift_reset_on_new_print(engine):
    engine.process(result(layer_shift=75))
    engine.start_print()
    assert not engine.layer_shift_detected
    d = engine.process(result(layer_shift=75))
    assert d.layer_shift_event


# -- reset() -----------------------------------------------------------------------


def test_reset_clears_detection_but_keeps_mute(engine):
    for _ in range(3):
        engine.process(result(stringing=60, warping=65))
    engine.process(result(spaghetti=75, layer_shift=75))
    engine.mute_current_print()

    engine.reset()

    assert not engine.stringing_detected
    assert not engine.warping_detected
    assert not engine.print_failure
    assert not engine.layer_shift_detected
    assert engine.muted  # mute untouched

    # cooldown timers cleared: next detection notifies immediately again
    engine.mute_current_print(False)
    for _ in range(3):
        d = engine.process(result(stringing=60))
    assert d.stringing_event
    d = engine.process(result(spaghetti=75))
    assert d.spaghetti_event


def test_start_print_clears_mute_and_state(engine):
    for _ in range(3):
        engine.process(result(stringing=60))
    engine.mute_current_print()
    engine.start_print()
    assert not engine.muted
    assert not engine.stringing_detected
