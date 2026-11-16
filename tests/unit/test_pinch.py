import pytest

from aircue.gestures.pinch import PinchEventKind, PinchState, PinchStateMachine
from aircue.vision.types import HandFeatures, HandRecord
from tests.fixtures.landmarks import make_landmarks


def hand(pinch_distance: float | None) -> HandRecord:
    return HandRecord(
        track_id=0,
        handedness="Right",
        confidence=0.9,
        landmarks=make_landmarks(),
        valid=(True,) * 21,
        features=HandFeatures(
            wrist_angle_deg=0.0,
            pinch_distance=pinch_distance,
            palm_scale=0.25,
            openness=1.0,
            finger_extension=(True,) * 5,
        ),
    )


def machine(**overrides) -> PinchStateMachine:
    settings = {
        "close_threshold": 0.22,
        "release_threshold": 0.32,
        "rearm_threshold": 0.40,
        "close_confirm_ms": 100,
        "release_confirm_ms": 100,
        "rearm_confirm_ms": 300,
    }
    settings.update(overrides)
    return PinchStateMachine(**settings)


def ms(value: int) -> int:
    return value * 1_000_000


def close_pinch(cycle: PinchStateMachine, start_ns: int) -> None:
    assert cycle.update(hand(0.20), start_ns) is None
    assert cycle.update(hand(0.20), start_ns + ms(100)) is not None


def release_pinch(cycle: PinchStateMachine, start_ns: int) -> None:
    assert cycle.update(hand(0.33), start_ns) is None
    assert cycle.update(hand(0.33), start_ns + ms(100)) is not None


def test_initiation_requires_the_full_window() -> None:
    cycle = machine()
    assert cycle.update(hand(0.20), 0) is None
    assert cycle.state is PinchState.CLOSING
    assert cycle.update(hand(0.20), ms(99)) is None
    event = cycle.update(hand(0.20), ms(100))
    assert event is not None
    assert event.kind is PinchEventKind.INITIATED
    assert event.onset_ns == 0
    assert event.timestamp_ns == ms(100)
    assert cycle.state is PinchState.PINCHED
    assert cycle.is_closed is True


def test_distance_at_close_threshold_is_not_a_pinch() -> None:
    cycle = machine()
    assert cycle.update(hand(0.22), 0) is None
    assert cycle.update(hand(0.22), ms(1000)) is None
    assert cycle.state is PinchState.ARMED


def test_release_requires_the_full_window() -> None:
    cycle = machine()
    close_pinch(cycle, 0)
    assert cycle.update(hand(0.33), ms(150)) is None
    assert cycle.state is PinchState.RELEASING
    assert cycle.update(hand(0.33), ms(249)) is None
    event = cycle.update(hand(0.33), ms(250))
    assert event is not None
    assert event.kind is PinchEventKind.RELEASED
    assert event.onset_ns == ms(150)
    assert event.held_ns == ms(150)
    assert cycle.state is PinchState.AWAITING_REARM


def test_distance_at_release_threshold_stays_pinched() -> None:
    cycle = machine()
    close_pinch(cycle, 0)
    assert cycle.update(hand(0.32), ms(1000)) is None
    assert cycle.state is PinchState.PINCHED


def test_hysteresis_band_does_not_start_a_second_pinch() -> None:
    cycle = machine()
    close_pinch(cycle, 0)
    for timestamp in range(200, 1200, 100):
        assert cycle.update(hand(0.25), ms(timestamp)) is None
    for timestamp in range(1200, 2200, 100):
        assert cycle.update(hand(0.21), ms(timestamp)) is None
    assert cycle.state is PinchState.PINCHED


def test_release_above_threshold_but_below_neutral_stays_unarmed() -> None:
    cycle = machine()
    close_pinch(cycle, 0)
    release_pinch(cycle, ms(100))
    for timestamp in range(300, 1300, 100):
        assert cycle.update(hand(0.35), ms(timestamp)) is None
    assert cycle.state is PinchState.AWAITING_REARM

    for timestamp in range(1300, 2300, 100):
        assert cycle.update(hand(0.21), ms(timestamp)) is None
    assert cycle.state is PinchState.AWAITING_REARM


def test_rearm_requires_neutral_above_threshold() -> None:
    cycle = machine()
    close_pinch(cycle, 0)
    release_pinch(cycle, ms(100))
    assert cycle.update(hand(0.41), ms(250)) is None
    assert cycle.update(hand(0.41), ms(449)) is None
    assert cycle.state is PinchState.AWAITING_REARM
    assert cycle.update(hand(0.41), ms(550)) is None
    assert cycle.state is PinchState.ARMED

    assert cycle.update(hand(0.20), ms(550)) is None
    event = cycle.update(hand(0.20), ms(650))
    assert event is not None
    assert event.kind is PinchEventKind.INITIATED


def test_rearm_timer_restarts_after_dropping_to_the_threshold() -> None:
    cycle = machine()
    close_pinch(cycle, 0)
    release_pinch(cycle, ms(100))
    assert cycle.update(hand(0.41), ms(250)) is None
    assert cycle.update(hand(0.40), ms(450)) is None
    assert cycle.update(hand(0.41), ms(550)) is None
    assert cycle.update(hand(0.41), ms(849)) is None
    assert cycle.state is PinchState.AWAITING_REARM
    assert cycle.update(hand(0.41), ms(850)) is None
    assert cycle.state is PinchState.ARMED


def test_partial_occlusion_cancels_a_pending_close() -> None:
    cycle = machine()
    assert cycle.update(hand(0.20), 0) is None
    assert cycle.update(None, ms(50)) is None
    assert cycle.state is PinchState.ARMED
    assert cycle.update(hand(0.20), ms(100)) is None
    assert cycle.update(hand(0.20), ms(199)) is None
    assert cycle.update(hand(0.20), ms(200)) is not None


def test_partial_occlusion_while_pinched_keeps_the_closed_state() -> None:
    cycle = machine()
    close_pinch(cycle, 0)
    assert cycle.update(None, ms(200)) is None
    assert cycle.state is PinchState.PINCHED
    assert cycle.update(hand(0.20), ms(300)) is None
    assert cycle.state is PinchState.PINCHED
    assert cycle.update(hand(0.33), ms(400)) is None
    assert cycle.update(hand(0.33), ms(499)) is None
    event = cycle.update(hand(0.33), ms(500))
    assert event is not None
    assert event.kind is PinchEventKind.RELEASED


def test_partial_occlusion_during_release_keeps_the_pinch_closed() -> None:
    cycle = machine()
    close_pinch(cycle, 0)
    assert cycle.update(hand(0.33), ms(100)) is None
    assert cycle.update(None, ms(150)) is None
    assert cycle.state is PinchState.PINCHED
    assert cycle.update(hand(0.33), ms(200)) is None
    assert cycle.update(hand(0.33), ms(299)) is None
    assert cycle.update(hand(0.33), ms(300)) is not None


def test_missing_distance_before_any_pinch_stays_armed() -> None:
    cycle = machine()
    assert cycle.update(hand(None), 0) is None
    assert cycle.update(None, ms(100)) is None
    assert cycle.state is PinchState.ARMED


def test_full_cycle_can_repeat_after_neutral_rearm() -> None:
    cycle = machine()
    close_pinch(cycle, 0)
    release_pinch(cycle, ms(100))
    assert cycle.update(hand(0.45), ms(250)) is None
    assert cycle.update(hand(0.45), ms(550)) is None
    assert cycle.state is PinchState.ARMED
    assert cycle.update(hand(0.20), ms(600)) is None
    second = cycle.update(hand(0.20), ms(700))
    assert second is not None
    assert second.kind is PinchEventKind.INITIATED
    assert second.onset_ns == ms(600)
    assert cycle.pinched_ns(ms(850)) == ms(150)


def test_zero_confirmation_windows_act_immediately() -> None:
    cycle = machine(
        close_confirm_ms=0, release_confirm_ms=0, rearm_confirm_ms=0
    )
    initiated = cycle.update(hand(0.20), 0)
    assert initiated is not None
    assert initiated.onset_ns == 0
    released = cycle.update(hand(0.50), ms(10))
    assert released is not None
    assert released.kind is PinchEventKind.RELEASED
    assert cycle.update(hand(0.50), ms(20)) is None
    assert cycle.state is PinchState.ARMED
    second = cycle.update(hand(0.20), ms(30))
    assert second is not None
    assert second.kind is PinchEventKind.INITIATED


def test_release_event_reports_held_duration() -> None:
    cycle = machine()
    close_pinch(cycle, 0)
    assert cycle.pinched_ns(ms(100)) == 0
    assert cycle.pinched_ns(ms(800)) == ms(700)
    assert cycle.update(hand(0.40), ms(900)) is None
    event = cycle.update(hand(0.40), ms(1000))
    assert event is not None
    assert event.held_ns == ms(900)
    assert cycle.pinched_ns(ms(1000)) is None


def test_reset_clears_the_cycle() -> None:
    cycle = machine()
    close_pinch(cycle, 0)
    cycle.reset()
    assert cycle.state is PinchState.ARMED
    assert cycle.update(hand(0.20), ms(200)) is None
    assert cycle.update(hand(0.20), ms(300)) is not None


@pytest.mark.parametrize("distance", [0.0, 0.1, 0.21])
def test_any_distance_below_close_threshold_can_initiate(distance: float) -> None:
    cycle = machine()
    assert cycle.update(hand(distance), 0) is None
    assert cycle.update(hand(distance), ms(100)) is not None


def test_events_carry_the_onset_frame_sequence() -> None:
    cycle = machine()
    assert cycle.update(hand(0.20), 0, sequence=30) is None
    initiated = cycle.update(hand(0.20), ms(100), sequence=31)
    assert initiated is not None
    assert initiated.onset_ns == 0
    assert initiated.onset_sequence == 30
    assert initiated.confidence == pytest.approx(0.9)

    assert cycle.update(hand(0.33), ms(200), sequence=32) is None
    released = cycle.update(hand(0.33), ms(300), sequence=33)
    assert released is not None
    assert released.onset_ns == ms(200)
    assert released.onset_sequence == 32
    assert released.confidence == pytest.approx(0.9)
