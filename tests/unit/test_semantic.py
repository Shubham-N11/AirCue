import pytest

from aircue.gestures.semantic import GestureAction, SemanticEvent, SemanticMapper
from aircue.gestures.vocabulary import Gesture
from aircue.state.states import InteractionState


def mapper(**overrides) -> SemanticMapper:
    settings = {
        "activation_hold_ms": 800,
        "resume_hold_ms": 250,
        "fist_confirm_ms": 200,
        "peace_confirm_ms": 250,
        "shaka_hold_ms": 1500,
        "gesture_cooldown_ms": 500,
        "rearm_ms": 300,
        "confidence_threshold": 0.5,
    }
    settings.update(overrides)
    return SemanticMapper(**settings)


def ms(value: int) -> int:
    return value * 1_000_000


def hold(
    subject: SemanticMapper,
    gesture: Gesture,
    state: InteractionState,
    hold_ms: int,
    *,
    confidence: float = 0.9,
) -> SemanticEvent | None:
    assert subject.update(gesture, confidence, state, 0) is None
    return subject.update(gesture, confidence, state, ms(hold_ms))


@pytest.mark.parametrize(
    ("state", "gesture", "window_ms", "action"),
    [
        (InteractionState.IDLE, Gesture.THUMBS_UP, 800, GestureAction.ACTIVATE),
        (
            InteractionState.PAUSED,
            Gesture.THUMBS_UP,
            250,
            GestureAction.RESUME_TRACKING,
        ),
        (
            InteractionState.ACTIVE,
            Gesture.FIST,
            200,
            GestureAction.PAUSE_TRACKING,
        ),
        (
            InteractionState.POINTER_MODE,
            Gesture.FIST,
            200,
            GestureAction.PAUSE_TRACKING,
        ),
        (
            InteractionState.SCROLL_MODE,
            Gesture.FIST,
            200,
            GestureAction.PAUSE_TRACKING,
        ),
        (
            InteractionState.ACTIVE,
            Gesture.PEACE,
            250,
            GestureAction.ENTER_SCROLL_MODE,
        ),
        (
            InteractionState.SCROLL_MODE,
            Gesture.PEACE,
            250,
            GestureAction.EXIT_SCROLL_MODE,
        ),
    ],
)
def test_context_mapping_uses_the_state_window(
    state: InteractionState,
    gesture: Gesture,
    window_ms: int,
    action: GestureAction,
) -> None:
    subject = mapper()
    assert hold(subject, gesture, state, window_ms - 1) is None
    event = hold(subject, gesture, state, window_ms)
    assert event is not None
    assert event.action is action
    assert event.gesture is gesture
    assert event.onset_ns == 0
    assert event.timestamp_ns == ms(window_ms)
    assert event.confidence == pytest.approx(0.9)


@pytest.mark.parametrize(
    "state",
    [InteractionState.ACTIVE, InteractionState.POINTER_MODE, InteractionState.SCROLL_MODE],
)
def test_thumbs_up_is_ignored_outside_activation_states(state: InteractionState) -> None:
    subject = mapper()
    for timestamp in range(0, 5000, 100):
        assert subject.update(Gesture.THUMBS_UP, 0.9, state, ms(timestamp)) is None


@pytest.mark.parametrize("state", [InteractionState.IDLE, InteractionState.PAUSED])
def test_fist_is_ignored_outside_active_states(state: InteractionState) -> None:
    subject = mapper()
    for timestamp in range(0, 5000, 100):
        assert subject.update(Gesture.FIST, 0.9, state, ms(timestamp)) is None


def test_peace_is_ignored_in_pointer_mode() -> None:
    subject = mapper()
    for timestamp in range(0, 5000, 100):
        assert (
            subject.update(Gesture.PEACE, 0.9, InteractionState.POINTER_MODE, ms(timestamp)) is None
        )


@pytest.mark.parametrize(
    "state",
    [
        InteractionState.IDLE,
        InteractionState.ACTIVE,
        InteractionState.PAUSED,
        InteractionState.POINTER_MODE,
        InteractionState.SCROLL_MODE,
        InteractionState.ERROR,
    ],
)
def test_shaka_exits_after_the_hold(state: InteractionState) -> None:
    subject = mapper()
    assert hold(subject, Gesture.SHAKA, state, 1499) is None
    event = hold(subject, Gesture.SHAKA, state, 1500)
    assert event is not None
    assert event.action is GestureAction.EXIT_REQUEST


@pytest.mark.parametrize("state", [InteractionState.INITIALIZING, InteractionState.EXITING])
def test_no_gesture_maps_in_initializing_or_exiting(state: InteractionState) -> None:
    subject = mapper()
    for gesture in Gesture:
        for timestamp in range(0, 3000, 100):
            assert subject.update(gesture, 0.9, state, ms(timestamp)) is None


def test_one_event_per_sustained_pose() -> None:
    subject = mapper()
    subject.update(Gesture.THUMBS_UP, 0.9, InteractionState.IDLE, 0)
    assert subject.update(Gesture.THUMBS_UP, 0.9, InteractionState.IDLE, ms(800)) is not None
    for timestamp in range(900, 5000, 100):
        assert subject.update(Gesture.THUMBS_UP, 0.9, InteractionState.IDLE, ms(timestamp)) is None


def test_release_before_the_window_cancels_the_hold() -> None:
    subject = mapper()
    assert subject.update(Gesture.THUMBS_UP, 0.9, InteractionState.IDLE, 0) is None
    assert subject.update(Gesture.THUMBS_UP, 0.9, InteractionState.IDLE, ms(500)) is None
    assert subject.update(None, 1.0, InteractionState.IDLE, ms(600)) is None
    assert subject.update(Gesture.THUMBS_UP, 0.9, InteractionState.IDLE, ms(700)) is None
    assert subject.update(Gesture.THUMBS_UP, 0.9, InteractionState.IDLE, ms(1499)) is None
    event = subject.update(Gesture.THUMBS_UP, 0.9, InteractionState.IDLE, ms(1500))
    assert event is not None
    assert event.onset_ns == ms(700)


def test_low_confidence_never_confirms() -> None:
    subject = mapper()
    for timestamp in range(0, 2000, 100):
        assert subject.update(Gesture.THUMBS_UP, 0.49, InteractionState.IDLE, ms(timestamp)) is None


def test_confidence_drop_restarts_the_hold() -> None:
    subject = mapper()
    subject.update(Gesture.THUMBS_UP, 0.9, InteractionState.IDLE, 0)
    assert subject.update(Gesture.THUMBS_UP, 0.4, InteractionState.IDLE, ms(700)) is None
    assert subject.update(Gesture.THUMBS_UP, 0.9, InteractionState.IDLE, ms(800)) is None
    event = subject.update(Gesture.THUMBS_UP, 0.9, InteractionState.IDLE, ms(1599))
    assert event is None
    event = subject.update(Gesture.THUMBS_UP, 0.9, InteractionState.IDLE, ms(1600))
    assert event is not None
    assert event.onset_ns == ms(800)


def test_state_change_clears_pending_confirmation() -> None:
    subject = mapper()
    subject.update(Gesture.THUMBS_UP, 0.9, InteractionState.IDLE, 0)
    subject.update(Gesture.THUMBS_UP, 0.9, InteractionState.IDLE, ms(700))
    assert subject.update(Gesture.THUMBS_UP, 0.9, InteractionState.PAUSED, ms(750)) is None
    assert subject.update(Gesture.THUMBS_UP, 0.9, InteractionState.PAUSED, ms(999)) is None
    event = subject.update(Gesture.THUMBS_UP, 0.9, InteractionState.PAUSED, ms(1000))
    assert event is not None
    assert event.action is GestureAction.RESUME_TRACKING
    assert event.onset_ns == ms(750)


def test_unmapped_gesture_cancels_another_pending_hold() -> None:
    subject = mapper()
    subject.update(Gesture.THUMBS_UP, 0.9, InteractionState.IDLE, 0)
    assert subject.update(Gesture.FIST, 0.9, InteractionState.IDLE, ms(700)) is None
    assert subject.update(Gesture.THUMBS_UP, 0.9, InteractionState.IDLE, ms(800)) is None
    assert subject.update(Gesture.THUMBS_UP, 0.9, InteractionState.IDLE, ms(1599)) is None
    assert subject.update(Gesture.THUMBS_UP, 0.9, InteractionState.IDLE, ms(1600)) is not None


def test_reset_clears_pending_and_confirmed_state() -> None:
    subject = mapper()
    subject.update(Gesture.THUMBS_UP, 0.9, InteractionState.IDLE, 0)
    assert subject.update(Gesture.THUMBS_UP, 0.9, InteractionState.IDLE, ms(800)) is not None
    subject.reset()
    assert subject.update(Gesture.THUMBS_UP, 0.9, InteractionState.IDLE, ms(900)) is None
    assert subject.update(Gesture.THUMBS_UP, 0.9, InteractionState.IDLE, ms(1699)) is None
    assert subject.update(Gesture.THUMBS_UP, 0.9, InteractionState.IDLE, ms(1700)) is not None


def test_onset_sequence_is_the_first_frame_of_the_hold() -> None:
    subject = mapper()
    assert (
        subject.update(Gesture.THUMBS_UP, 0.9, InteractionState.IDLE, 0, sequence=20)
        is None
    )
    assert (
        subject.update(
            Gesture.THUMBS_UP, 0.9, InteractionState.IDLE, ms(400), sequence=21
        )
        is None
    )
    event = subject.update(
        Gesture.THUMBS_UP, 0.9, InteractionState.IDLE, ms(800), sequence=22
    )
    assert event is not None
    assert event.onset_ns == 0
    assert event.onset_sequence == 20
