import pytest

from aircue.gestures.pinch import PinchGestureRecognizer
from aircue.gestures.semantic import GestureAction, SemanticEvent
from aircue.gestures.vocabulary import Gesture
from aircue.state.states import InteractionState
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


def recognizer(**overrides) -> PinchGestureRecognizer:
    settings = {"long_pinch_ms": 700}
    settings.update(overrides)
    return PinchGestureRecognizer(**settings)


def ms(value: int) -> int:
    return value * 1_000_000


def start_pinch(
    subject: PinchGestureRecognizer, state: InteractionState, start_ns: int
) -> SemanticEvent | None:
    assert subject.update(hand(0.20), state, start_ns) is None
    return subject.update(hand(0.20), state, start_ns + ms(100))


def release_pinch(
    subject: PinchGestureRecognizer,
    state: InteractionState,
    start_ns: int,
    *,
    distance: float = 0.33,
) -> SemanticEvent | None:
    assert subject.update(hand(distance), state, start_ns) is None
    return subject.update(hand(distance), state, start_ns + ms(100))


def test_pinch_in_active_enters_pointer_mode_and_is_consumed() -> None:
    subject = recognizer()
    event = start_pinch(subject, InteractionState.ACTIVE, 0)
    assert event is not None
    assert event.action is GestureAction.ENTER_POINTER_MODE
    assert event.gesture is Gesture.PINCH
    assert event.onset_ns == 0
    assert event.timestamp_ns == ms(100)
    assert event.confidence == pytest.approx(0.9)

    assert subject.update(hand(0.20), InteractionState.POINTER_MODE, ms(200)) is None
    assert release_pinch(subject, InteractionState.POINTER_MODE, ms(300)) is None


def test_entry_pinch_never_clicks_even_after_state_change() -> None:
    subject = recognizer()
    assert start_pinch(subject, InteractionState.ACTIVE, 0) is not None
    assert release_pinch(subject, InteractionState.ACTIVE, ms(200)) is None
    assert subject.update(hand(0.50), InteractionState.ACTIVE, ms(400)) is None
    assert subject.update(hand(0.50), InteractionState.ACTIVE, ms(700)) is None
    assert start_pinch(subject, InteractionState.ACTIVE, ms(800)) is not None
    assert release_pinch(subject, InteractionState.ACTIVE, ms(600)) is None


def test_new_cycle_in_pointer_mode_emits_a_click_candidate() -> None:
    subject = recognizer()
    assert start_pinch(subject, InteractionState.ACTIVE, 0) is not None
    assert release_pinch(subject, InteractionState.POINTER_MODE, ms(200)) is None
    assert subject.update(hand(0.50), InteractionState.POINTER_MODE, ms(400)) is None
    assert subject.update(hand(0.50), InteractionState.POINTER_MODE, ms(700)) is None

    assert start_pinch(subject, InteractionState.POINTER_MODE, ms(800)) is None
    event = release_pinch(subject, InteractionState.POINTER_MODE, ms(1000))
    assert event is not None
    assert event.action is GestureAction.CLICK_CANDIDATE
    assert event.gesture is Gesture.PINCH_RELEASE
    assert event.onset_ns == ms(1000)
    assert event.timestamp_ns == ms(1100)


def test_click_candidate_onset_is_the_release_predicate() -> None:
    subject = recognizer()
    start_pinch(subject, InteractionState.POINTER_MODE, 0)
    assert subject.update(hand(0.33), InteractionState.POINTER_MODE, ms(400)) is None
    assert subject.update(hand(0.33), InteractionState.POINTER_MODE, ms(450)) is None
    event = subject.update(hand(0.33), InteractionState.POINTER_MODE, ms(550))
    assert event is not None
    assert event.action is GestureAction.CLICK_CANDIDATE
    assert event.onset_ns == ms(400)


def test_long_pinch_exits_pointer_mode_once() -> None:
    subject = recognizer()
    start_pinch(subject, InteractionState.POINTER_MODE, 0)
    assert subject.update(hand(0.20), InteractionState.POINTER_MODE, ms(799)) is None
    event = subject.update(hand(0.20), InteractionState.POINTER_MODE, ms(800))
    assert event is not None
    assert event.action is GestureAction.EXIT_POINTER_MODE
    assert event.gesture is Gesture.PINCH
    assert event.onset_ns == 0
    assert event.timestamp_ns == ms(800)

    for timestamp in range(900, 3000, 100):
        assert (
            subject.update(hand(0.20), InteractionState.POINTER_MODE, ms(timestamp))
            is None
        )


def test_long_pinch_suppresses_the_release_click() -> None:
    subject = recognizer()
    start_pinch(subject, InteractionState.POINTER_MODE, 0)
    assert subject.update(hand(0.20), InteractionState.POINTER_MODE, ms(800)) is not None
    assert release_pinch(subject, InteractionState.POINTER_MODE, ms(900)) is None
    assert subject.update(hand(0.50), InteractionState.POINTER_MODE, ms(1100)) is None
    assert subject.update(hand(0.50), InteractionState.POINTER_MODE, ms(1400)) is None
    assert start_pinch(subject, InteractionState.POINTER_MODE, ms(1500)) is None
    event = release_pinch(subject, InteractionState.POINTER_MODE, ms(1700))
    assert event is not None
    assert event.action is GestureAction.CLICK_CANDIDATE


def test_release_before_long_pinch_still_clicks() -> None:
    subject = recognizer()
    start_pinch(subject, InteractionState.POINTER_MODE, 0)
    assert release_pinch(subject, InteractionState.POINTER_MODE, ms(500)) is not None


def test_long_pinch_with_sparse_frames_suppresses_the_click() -> None:
    subject = recognizer()
    start_pinch(subject, InteractionState.POINTER_MODE, 0)
    assert subject.update(hand(0.33), InteractionState.POINTER_MODE, ms(850)) is None
    event = subject.update(hand(0.33), InteractionState.POINTER_MODE, ms(950))
    assert event is not None
    assert event.action is GestureAction.EXIT_POINTER_MODE
    assert event.onset_ns == 0


def test_release_before_the_long_pinch_boundary_clicks() -> None:
    subject = recognizer()
    start_pinch(subject, InteractionState.POINTER_MODE, 0)
    assert subject.update(hand(0.33), InteractionState.POINTER_MODE, ms(799)) is None
    event = subject.update(hand(0.33), InteractionState.POINTER_MODE, ms(899))
    assert event is not None
    assert event.action is GestureAction.CLICK_CANDIDATE


def test_pointer_movement_alone_never_clicks_or_changes_mode() -> None:
    subject = recognizer()
    for timestamp in range(0, 3000, 50):
        assert (
            subject.update(hand(0.50), InteractionState.POINTER_MODE, ms(timestamp))
            is None
        )
    assert subject.pinch_state.value == "armed"


@pytest.mark.parametrize(
    "state",
    [
        InteractionState.IDLE,
        InteractionState.PAUSED,
        InteractionState.SCROLL_MODE,
        InteractionState.ERROR,
    ],
)
def test_pinch_outside_pointer_states_emits_nothing(
    state: InteractionState,
) -> None:
    subject = recognizer()
    assert start_pinch(subject, state, 0) is None
    assert release_pinch(subject, state, ms(200)) is None


def test_pinch_held_in_active_never_emits_exit() -> None:
    subject = recognizer()
    assert start_pinch(subject, InteractionState.ACTIVE, 0) is not None
    for timestamp in range(100, 3000, 100):
        assert subject.update(hand(0.20), InteractionState.ACTIVE, ms(timestamp)) is None
    assert release_pinch(subject, InteractionState.ACTIVE, ms(3000)) is None


def test_occluded_pinch_emits_nothing() -> None:
    subject = recognizer()
    assert subject.update(hand(None), InteractionState.POINTER_MODE, 0) is None
    assert subject.update(None, InteractionState.POINTER_MODE, ms(500)) is None
    assert subject.update(hand(0.20), InteractionState.POINTER_MODE, ms(600)) is None
    assert subject.update(hand(0.33), InteractionState.POINTER_MODE, ms(900)) is None
    assert subject.update(hand(0.33), InteractionState.POINTER_MODE, ms(1000)) is None


def test_state_change_consumes_the_entry_pinch_release() -> None:
    subject = recognizer()
    assert start_pinch(subject, InteractionState.ACTIVE, 0) is not None
    assert release_pinch(subject, InteractionState.PAUSED, ms(200)) is None
    assert subject.update(hand(0.50), InteractionState.ACTIVE, ms(400)) is None
    assert subject.update(hand(0.50), InteractionState.ACTIVE, ms(700)) is None
    assert start_pinch(subject, InteractionState.ACTIVE, ms(800)) is not None


def test_reset_clears_consumption_flags() -> None:
    subject = recognizer()
    assert start_pinch(subject, InteractionState.ACTIVE, 0) is not None
    subject.reset()
    assert subject.pinch_state.value == "armed"
    assert start_pinch(subject, InteractionState.ACTIVE, ms(200)) is not None
