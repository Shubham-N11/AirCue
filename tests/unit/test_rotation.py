import pytest

from aircue.gestures.rotation import RotationDetector, RotationDirection
from aircue.vision.types import HandFeatures, HandRecord
from tests.fixtures.landmarks import make_landmarks


def hand(wrist_angle_deg: float | None, *, open_palm: bool = True) -> HandRecord:
    extension = (True, True, True, True, True) if open_palm else (False,) * 5
    return HandRecord(
        track_id=0,
        handedness="Right",
        confidence=0.9,
        landmarks=make_landmarks(),
        valid=(True,) * 21,
        features=HandFeatures(
            wrist_angle_deg=wrist_angle_deg,
            pinch_distance=1.0,
            palm_scale=0.25,
            openness=1.0 if open_palm else 0.0,
            finger_extension=extension,
        ),
    )


def detector(**overrides) -> RotationDetector:
    settings = {
        "activation_deg": 25.0,
        "neutral_band_deg": 8.0,
        "continuous_enabled": False,
        "repeat_step_deg": 30.0,
        "repeat_interval_ms": 400,
        "max_events_per_second": 2.0,
    }
    settings.update(overrides)
    return RotationDetector(**settings)


def test_clockwise_user_rotation_emits_clockwise() -> None:
    rotation = detector()
    assert rotation.update(hand(0.0), 0) is None
    assert rotation.update(hand(-24.0), 33_000_000) is None
    event = rotation.update(hand(-30.0), 66_000_000)
    assert event is not None
    assert event.direction is RotationDirection.CLOCKWISE
    assert event.delta_deg == pytest.approx(30.0)
    assert event.timestamp_ns == 66_000_000


def test_counterclockwise_user_rotation_emits_counterclockwise() -> None:
    rotation = detector()
    rotation.update(hand(0.0), 0)
    event = rotation.update(hand(30.0), 33_000_000)
    assert event is not None
    assert event.direction is RotationDirection.COUNTERCLOCKWISE
    assert event.delta_deg == pytest.approx(-30.0)


def test_neutral_band_suppresses_jitter() -> None:
    rotation = detector()
    rotation.update(hand(0.0), 0)
    angles = [-7.0, 7.0, -7.0, 7.0, 0.0]
    events = [
        rotation.update(hand(angle), index * 33_000_000)
        for index, angle in enumerate(angles, start=1)
    ]
    assert all(event is None for event in events)


def test_below_threshold_rotation_emits_nothing() -> None:
    rotation = detector()
    rotation.update(hand(0.0), 0)
    assert rotation.update(hand(-24.9), 33_000_000) is None
    assert rotation.update(hand(24.9), 66_000_000) is None


def test_activation_boundary() -> None:
    rotation = detector()
    rotation.update(hand(0.0), 0)
    at_boundary = rotation.update(hand(-25.0), 33_000_000)
    assert at_boundary is not None
    assert at_boundary.direction is RotationDirection.CLOCKWISE


def test_neutral_band_boundary_does_not_emit() -> None:
    rotation = detector()
    rotation.update(hand(0.0), 0)
    assert rotation.update(hand(-8.0), 33_000_000) is None


def test_one_event_per_continuous_pose_when_repeat_is_disabled() -> None:
    rotation = detector()
    rotation.update(hand(0.0), 0)
    first = rotation.update(hand(-30.0), 33_000_000)
    assert first is not None
    assert rotation.update(hand(-60.0), 66_000_000) is None
    assert rotation.update(hand(-90.0), 99_000_000) is None


def test_return_to_neutral_rearms_the_same_direction() -> None:
    rotation = detector()
    rotation.update(hand(0.0), 0)
    assert rotation.update(hand(-30.0), 33_000_000) is not None
    assert rotation.update(hand(-3.0), 66_000_000) is None
    second = rotation.update(hand(-33.0), 99_000_000)
    assert second is not None
    assert second.direction is RotationDirection.CLOCKWISE


def test_reversal_emits_the_opposite_direction() -> None:
    rotation = detector()
    rotation.update(hand(0.0), 0)
    assert rotation.update(hand(-30.0), 33_000_000) is not None
    reversed_event = rotation.update(hand(30.0), 66_000_000)
    assert reversed_event is not None
    assert reversed_event.direction is RotationDirection.COUNTERCLOCKWISE


def test_continuous_repeats_use_the_configured_step() -> None:
    rotation = detector(
        continuous_enabled=True,
        repeat_step_deg=30.0,
        repeat_interval_ms=0,
        max_events_per_second=10.0,
    )
    rotation.update(hand(0.0), 0)
    events = [
        rotation.update(hand(angle), timestamp_ns)
        for angle, timestamp_ns in [
            (-30.0, 1_000_000),
            (-59.0, 2_000_000),
            (-60.0, 3_000_000),
            (-89.0, 4_000_000),
            (-90.0, 5_000_000),
        ]
    ]
    emitted = [event for event in events if event is not None]
    assert len(emitted) == 3
    assert [event.delta_deg for event in emitted] == pytest.approx([30.0, 60.0, 90.0])


def test_continuous_repeats_respect_the_minimum_interval() -> None:
    rotation = detector(
        continuous_enabled=True,
        repeat_step_deg=10.0,
        repeat_interval_ms=400,
        max_events_per_second=10.0,
    )
    rotation.update(hand(0.0), 0)
    activation = rotation.update(hand(-30.0), 1_000_000)
    assert activation is not None
    early = rotation.update(hand(-50.0), 100_000_000)
    assert early is None
    on_time = rotation.update(hand(-50.0), 401_000_000)
    assert on_time is not None


def test_continuous_repeats_respect_the_maximum_rate() -> None:
    rotation = detector(
        continuous_enabled=True,
        repeat_step_deg=10.0,
        repeat_interval_ms=0,
        max_events_per_second=2.0,
    )
    rotation.update(hand(0.0), 0)
    activation = rotation.update(hand(-30.0), 1_000_000)
    repeat_one = rotation.update(hand(-50.0), 2_000_000)
    capped = rotation.update(hand(-70.0), 3_000_000)
    window_cleared = rotation.update(hand(-70.0), 1_003_000_000)
    assert activation is not None
    assert repeat_one is not None
    assert capped is None
    assert window_cleared is not None


def test_pose_loss_resets_the_neutral_reference() -> None:
    rotation = detector()
    rotation.update(hand(0.0), 0)
    assert rotation.update(None, 33_000_000) is None
    assert rotation.update(hand(-30.0), 66_000_000) is None
    event = rotation.update(hand(-60.0), 99_000_000)
    assert event is not None
    assert event.direction is RotationDirection.CLOCKWISE


def test_wrist_angle_unavailable_resets_the_reference() -> None:
    rotation = detector()
    rotation.update(hand(0.0), 0)
    assert rotation.update(hand(None), 33_000_000) is None
    assert rotation.update(hand(-30.0), 66_000_000) is None
    assert rotation.update(hand(-60.0), 99_000_000) is not None


def test_closed_fist_does_not_rotate() -> None:
    rotation = detector()
    rotation.update(hand(0.0), 0)
    assert rotation.update(hand(-30.0, open_palm=False), 33_000_000) is None
    assert rotation.update(hand(-60.0, open_palm=False), 66_000_000) is None


def test_reset_clears_repeat_state() -> None:
    rotation = detector(continuous_enabled=True, repeat_interval_ms=0)
    rotation.update(hand(0.0), 0)
    assert rotation.update(hand(-30.0), 1_000_000) is not None
    rotation.reset()
    assert rotation.update(hand(-60.0), 2_000_000) is None
    assert rotation.update(hand(-90.0), 3_000_000) is not None
