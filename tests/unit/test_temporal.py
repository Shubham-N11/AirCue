import pytest

from aircue.gestures.temporal import ConfirmedGesture, TemporalValidator
from aircue.gestures.vocabulary import Gesture

WINDOWS = {Gesture.FIST: 200, Gesture.PEACE: 250, Gesture.SHAKA: 1000}


def make_validator(
    windows=None,
    *,
    cooldown_ms: int = 500,
    rearm_ms: int = 300,
    confidence_threshold: float = 0.5,
) -> TemporalValidator:
    return TemporalValidator(
        WINDOWS if windows is None else windows,
        cooldown_ms=cooldown_ms,
        rearm_ms=rearm_ms,
        confidence_threshold=confidence_threshold,
    )


def ms(value: int) -> int:
    return value * 1_000_000


@pytest.mark.parametrize(
    ("gesture", "window_ms"),
    [(Gesture.FIST, 200), (Gesture.PEACE, 250), (Gesture.SHAKA, 1000)],
)
def test_confirms_at_the_configured_window(gesture: Gesture, window_ms: int) -> None:
    validator = make_validator()
    assert validator.update(gesture, 0.9, 0) is None
    assert validator.update(gesture, 0.9, ms(window_ms - 1)) is None
    event = validator.update(gesture, 0.9, ms(window_ms))
    assert isinstance(event, ConfirmedGesture)
    assert event.gesture is gesture
    assert event.onset_ns == 0
    assert event.timestamp_ns == ms(window_ms)
    assert event.confidence == pytest.approx(0.9)


def test_pose_change_before_the_window_cancels_confirmation() -> None:
    validator = make_validator()
    assert validator.update(Gesture.FIST, 0.9, 0) is None
    assert validator.update(Gesture.FIST, 0.9, ms(100)) is None
    assert validator.update(Gesture.PEACE, 0.9, ms(150)) is None
    assert validator.update(Gesture.FIST, 0.9, ms(300)) is None
    assert validator.update(Gesture.FIST, 0.9, ms(499)) is None
    event = validator.update(Gesture.FIST, 0.9, ms(500))
    assert event is not None
    assert event.onset_ns == ms(300)


def test_one_event_per_sustained_pose() -> None:
    validator = make_validator()
    validator.update(Gesture.FIST, 0.9, 0)
    assert validator.update(Gesture.FIST, 0.9, ms(200)) is not None
    assert validator.update(Gesture.FIST, 0.9, ms(233)) is None
    assert validator.update(Gesture.FIST, 0.9, ms(400)) is None
    assert validator.update(Gesture.FIST, 0.9, ms(1000)) is None
    assert validator.update(Gesture.FIST, 0.9, ms(2000)) is None


def test_neutral_rearm_allows_a_second_event() -> None:
    validator = make_validator()
    validator.update(Gesture.FIST, 0.9, 0)
    assert validator.update(Gesture.FIST, 0.9, ms(200)) is not None
    assert validator.update(None, 1.0, ms(200)) is None
    assert validator.update(None, 1.0, ms(499)) is None
    assert validator.update(None, 1.0, ms(500)) is None
    assert validator.update(Gesture.FIST, 0.9, ms(500)) is None
    event = validator.update(Gesture.FIST, 0.9, ms(700))
    assert event is not None
    assert event.gesture is Gesture.FIST


def test_different_pose_interrupts_rearm() -> None:
    validator = make_validator()
    validator.update(Gesture.FIST, 0.9, 0)
    assert validator.update(Gesture.FIST, 0.9, ms(200)) is not None
    assert validator.update(None, 1.0, ms(300)) is None
    assert validator.update(Gesture.FIST, 0.9, ms(400)) is None
    assert validator.update(None, 1.0, ms(450)) is None
    assert validator.update(None, 1.0, ms(700)) is None
    assert validator.update(Gesture.FIST, 0.9, ms(750)) is None
    assert validator.update(Gesture.FIST, 0.9, ms(1000)) is None
    assert validator.update(None, 1.0, ms(1001)) is None
    assert validator.update(None, 1.0, ms(1301)) is None
    assert validator.update(Gesture.FIST, 0.9, ms(1301)) is None
    event = validator.update(Gesture.FIST, 0.9, ms(1501))
    assert event is not None


def test_cooldown_suppresses_a_repeat() -> None:
    validator = make_validator(
        {Gesture.FIST: 100},
        cooldown_ms=1000,
        rearm_ms=100,
    )
    validator.update(Gesture.FIST, 0.9, 0)
    assert validator.update(Gesture.FIST, 0.9, ms(100)) is not None
    validator.update(None, 1.0, ms(200))
    validator.update(None, 1.0, ms(300))
    validator.update(Gesture.FIST, 0.9, ms(300))
    assert validator.update(Gesture.FIST, 0.9, ms(400)) is None
    assert validator.update(Gesture.FIST, 0.9, ms(500)) is None
    validator.update(None, 1.0, ms(600))
    validator.update(None, 1.0, ms(700))
    validator.update(Gesture.FIST, 0.9, ms(1000))
    event = validator.update(Gesture.FIST, 0.9, ms(1100))
    assert event is not None


def test_low_confidence_cancels_a_pending_confirmation() -> None:
    validator = make_validator()
    assert validator.update(Gesture.FIST, 0.4, 0) is None
    assert validator.update(Gesture.FIST, 0.4, ms(100)) is None
    assert validator.update(Gesture.FIST, 0.4, ms(199)) is None
    assert validator.update(Gesture.FIST, 0.9, ms(200)) is None
    assert validator.update(Gesture.FIST, 0.9, ms(399)) is None
    event = validator.update(Gesture.FIST, 0.9, ms(400))
    assert event is not None
    assert event.onset_ns == ms(200)
    assert event.confidence == pytest.approx(0.9)


def test_confidence_drop_cancels_a_pending_confirmation() -> None:
    validator = make_validator()
    validator.update(Gesture.FIST, 0.9, 0)
    assert validator.update(Gesture.FIST, 0.4, ms(100)) is None
    assert validator.update(Gesture.FIST, 0.9, ms(200)) is None
    assert validator.update(Gesture.FIST, 0.9, ms(399)) is None
    event = validator.update(Gesture.FIST, 0.9, ms(400))
    assert event is not None
    assert event.onset_ns == ms(200)


def test_low_confidence_does_not_rearm_a_confirmed_gesture() -> None:
    validator = make_validator()
    validator.update(Gesture.FIST, 0.9, 0)
    assert validator.update(Gesture.FIST, 0.9, ms(200)) is not None
    for timestamp in (300, 400, 500, 600, 700):
        assert validator.update(Gesture.FIST, 0.4, ms(timestamp)) is None
    assert validator.update(Gesture.FIST, 0.9, ms(700)) is None
    assert validator.update(Gesture.FIST, 0.9, ms(900)) is None


def test_unconfigured_gesture_is_rejected() -> None:
    validator = make_validator({Gesture.FIST: 100})
    with pytest.raises(ValueError, match="no confirmation window"):
        validator.update(Gesture.PEACE, 0.9, 0)


def test_reset_clears_confirmation_and_rearm_state() -> None:
    validator = make_validator({Gesture.FIST: 100})
    validator.update(Gesture.FIST, 0.9, 0)
    assert validator.update(Gesture.FIST, 0.9, ms(100)) is not None
    validator.reset()
    assert validator.update(Gesture.FIST, 0.9, ms(200)) is None
    event = validator.update(Gesture.FIST, 0.9, ms(300))
    assert event is not None
