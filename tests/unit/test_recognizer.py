import pytest

from aircue.config.loader import parse_config
from aircue.config.schema import Config
from aircue.gestures.recognizer import GestureRecognizer, static_gesture
from aircue.gestures.semantic import GestureAction
from aircue.gestures.vocabulary import Gesture
from aircue.state.states import InteractionState
from aircue.vision.types import THUMB_MCP, THUMB_TIP, HandFeatures, HandRecord
from tests.fixtures.landmarks import BASE_POSE, make_landmarks

OPEN_PALM = (True, True, True, True, True)
FIST = (False, False, False, False, False)
THUMBS_UP = (True, False, False, False, False)
PEACE = (False, True, True, False, False)
SHAKA = (True, False, False, False, True)


def hand(
    extensions: tuple[bool, ...],
    *,
    pinch_distance: float = 1.0,
    wrist_angle_deg: float = 0.0,
    thumb_up: bool = False,
) -> HandRecord:
    overrides = {}
    if thumb_up:
        mcp_x, mcp_y, _ = BASE_POSE[THUMB_MCP]
        overrides[THUMB_TIP] = (mcp_x, mcp_y - 0.3, 0.0, 0.9)
    return HandRecord(
        track_id=0,
        handedness="Right",
        confidence=0.9,
        landmarks=make_landmarks(overrides),
        valid=(True,) * 21,
        features=HandFeatures(
            wrist_angle_deg=wrist_angle_deg,
            pinch_distance=pinch_distance,
            palm_scale=0.25,
            openness=None,
            finger_extension=extensions,
        ),
    )


def ms(value: int) -> int:
    return value * 1_000_000


def test_static_gesture_uses_the_fixed_patterns() -> None:
    assert static_gesture(hand(FIST)) is Gesture.FIST
    assert static_gesture(hand(THUMBS_UP, thumb_up=True)) is Gesture.THUMBS_UP
    assert static_gesture(hand(PEACE)) is Gesture.PEACE
    assert static_gesture(hand(SHAKA)) is Gesture.SHAKA
    assert static_gesture(hand(OPEN_PALM)) is None
    assert static_gesture(None) is None


def test_thumbs_up_activates_after_the_default_hold() -> None:
    subject = GestureRecognizer(Config())
    pose = hand(THUMBS_UP, thumb_up=True)
    assert subject.update(pose, InteractionState.IDLE, 0, sequence=1) is None
    assert subject.update(pose, InteractionState.IDLE, ms(799), sequence=2) is None
    event = subject.update(pose, InteractionState.IDLE, ms(800), sequence=3)
    assert event is not None
    assert event.action is GestureAction.ACTIVATE
    assert event.gesture is Gesture.THUMBS_UP
    assert event.onset_sequence == 1


def test_config_changes_activation_hold() -> None:
    config = parse_config({"timing": {"activation_hold_ms": 300}})
    subject = GestureRecognizer(config)
    pose = hand(THUMBS_UP, thumb_up=True)
    assert subject.update(pose, InteractionState.IDLE, 0, sequence=1) is None
    assert subject.update(pose, InteractionState.IDLE, ms(299), sequence=2) is None
    event = subject.update(pose, InteractionState.IDLE, ms(300), sequence=3)
    assert event is not None
    assert event.action is GestureAction.ACTIVATE


def test_config_changes_fist_confirmation() -> None:
    config = parse_config({"timing": {"fist_confirm_ms": 50}})
    subject = GestureRecognizer(config)
    pose = hand(FIST)
    assert subject.update(pose, InteractionState.ACTIVE, 0, sequence=1) is None
    assert subject.update(pose, InteractionState.ACTIVE, ms(49), sequence=2) is None
    event = subject.update(pose, InteractionState.ACTIVE, ms(50), sequence=3)
    assert event is not None
    assert event.action is GestureAction.PAUSE_TRACKING


def test_default_rotation_activation() -> None:
    subject = GestureRecognizer(Config())
    assert (
        subject.update(
            hand(OPEN_PALM, wrist_angle_deg=0.0),
            InteractionState.ACTIVE,
            0,
            sequence=1,
        )
        is None
    )
    event = subject.update(
        hand(OPEN_PALM, wrist_angle_deg=-30.0),
        InteractionState.ACTIVE,
        ms(100),
        sequence=2,
    )
    assert event is not None
    assert event.action is GestureAction.NEXT_SLIDE
    assert event.gesture is Gesture.OPEN_PALM_CLOCKWISE


def test_config_changes_rotation_activation() -> None:
    config = parse_config({"rotation": {"activation_deg": 45.0}})
    subject = GestureRecognizer(config)
    assert (
        subject.update(
            hand(OPEN_PALM, wrist_angle_deg=0.0),
            InteractionState.ACTIVE,
            0,
            sequence=1,
        )
        is None
    )
    assert (
        subject.update(
            hand(OPEN_PALM, wrist_angle_deg=-44.0),
            InteractionState.ACTIVE,
            ms(100),
            sequence=2,
        )
        is None
    )
    event = subject.update(
        hand(OPEN_PALM, wrist_angle_deg=-45.0),
        InteractionState.ACTIVE,
        ms(200),
        sequence=3,
    )
    assert event is not None
    assert event.action is GestureAction.NEXT_SLIDE


def test_counterclockwise_rotation_maps_to_previous_slide() -> None:
    subject = GestureRecognizer(Config())
    subject.update(hand(OPEN_PALM, wrist_angle_deg=0.0), InteractionState.ACTIVE, 0)
    event = subject.update(
        hand(OPEN_PALM, wrist_angle_deg=30.0), InteractionState.ACTIVE, ms(100)
    )
    assert event is not None
    assert event.action is GestureAction.PREV_SLIDE
    assert event.gesture is Gesture.OPEN_PALM_COUNTERCLOCKWISE


def test_config_changes_pinch_close_threshold() -> None:
    default = GestureRecognizer(Config())
    assert (
        default.update(hand(OPEN_PALM, pinch_distance=0.20), InteractionState.ACTIVE, 0)
        is None
    )
    entry = default.update(
        hand(OPEN_PALM, pinch_distance=0.20), InteractionState.ACTIVE, ms(100)
    )
    assert entry is not None
    assert entry.action is GestureAction.ENTER_POINTER_MODE

    config = parse_config(
        {
            "pinch": {
                "close_threshold": 0.10,
                "release_threshold": 0.20,
                "rearm_threshold": 0.30,
            }
        }
    )
    subject = GestureRecognizer(config)
    for timestamp in range(0, 1000, 100):
        assert (
            subject.update(
                hand(OPEN_PALM, pinch_distance=0.20),
                InteractionState.ACTIVE,
                ms(timestamp),
            )
            is None
        )
    assert (
        subject.update(
            hand(OPEN_PALM, pinch_distance=0.05), InteractionState.ACTIVE, ms(1000)
        )
        is None
    )
    event = subject.update(
        hand(OPEN_PALM, pinch_distance=0.05), InteractionState.ACTIVE, ms(1100)
    )
    assert event is not None
    assert event.action is GestureAction.ENTER_POINTER_MODE


def test_config_changes_long_pinch_window() -> None:
    config = parse_config({"timing": {"long_pinch_ms": 1000}})
    subject = GestureRecognizer(config)
    assert (
        subject.update(
            hand(OPEN_PALM, pinch_distance=0.10),
            InteractionState.POINTER_MODE,
            0,
        )
        is None
    )
    assert (
        subject.update(
            hand(OPEN_PALM, pinch_distance=0.10),
            InteractionState.POINTER_MODE,
            ms(100),
        )
        is None
    )
    assert (
        subject.update(
            hand(OPEN_PALM, pinch_distance=0.10),
            InteractionState.POINTER_MODE,
            ms(1099),
        )
        is None
    )
    event = subject.update(
        hand(OPEN_PALM, pinch_distance=0.10),
        InteractionState.POINTER_MODE,
        ms(1100),
    )
    assert event is not None
    assert event.action is GestureAction.EXIT_POINTER_MODE


def test_config_changes_shaka_hold() -> None:
    config = parse_config({"timing": {"shaka_hold_ms": 200}})
    subject = GestureRecognizer(config)
    pose = hand(SHAKA)
    assert subject.update(pose, InteractionState.ERROR, 0) is None
    event = subject.update(pose, InteractionState.ERROR, ms(200))
    assert event is not None
    assert event.action is GestureAction.EXIT_REQUEST


def test_invalid_config_change_is_rejected() -> None:
    with pytest.raises(ValueError, match="must be >= 1"):
        parse_config({"timing": {"activation_hold_ms": 0}})
