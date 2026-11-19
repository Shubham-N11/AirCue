from __future__ import annotations

import pytest

from aircue.commands.click import ClickController, ClickDispatch, ClickUpdate
from aircue.gestures.semantic import GestureAction, SemanticEvent
from aircue.gestures.vocabulary import Gesture
from aircue.performance.timing import FrameTimings
from aircue.state.machine import StateMachine
from aircue.state.states import InteractionState
from aircue.state.transitions import TransitionTrigger

MS = 1_000_000
WINDOW = 350


def event(
    action: GestureAction,
    timestamp_ms: int,
    *,
    gesture: Gesture = Gesture.PINCH_RELEASE,
) -> SemanticEvent:
    return SemanticEvent(
        action=action,
        gesture=gesture,
        onset_ns=timestamp_ms * MS,
        onset_sequence=0,
        timestamp_ns=timestamp_ms * MS,
        confidence=0.9,
    )


def controller(state: InteractionState = InteractionState.POINTER_MODE) -> ClickController:
    return ClickController(StateMachine(state))


def candidate(timestamp_ms: int) -> SemanticEvent:
    return event(GestureAction.CLICK_CANDIDATE, timestamp_ms)


def long_pinch(timestamp_ms: int) -> SemanticEvent:
    return event(GestureAction.EXIT_POINTER_MODE, timestamp_ms, gesture=Gesture.PINCH)


def test_a_candidate_in_pointer_mode_starts_the_window() -> None:
    subject = controller()
    assert subject.on_event(candidate(0)) == ClickUpdate()
    assert subject.pending is True


def test_a_second_candidate_in_pointer_mode_dispatches_one_double_click() -> None:
    subject = controller()
    subject.on_event(candidate(0))
    assert subject.on_event(candidate(200)) == ClickUpdate(dispatch=ClickDispatch.DOUBLE)
    assert subject.pending is False
    assert subject.advance(10_000 * MS) == ClickUpdate()


def test_the_expired_window_dispatches_one_single_click() -> None:
    subject = controller()
    subject.on_event(candidate(0))
    assert subject.advance(WINDOW * MS - 1) == ClickUpdate()
    assert subject.advance(WINDOW * MS) == ClickUpdate(dispatch=ClickDispatch.SINGLE)


def test_long_pinch_while_pending_cancels_the_click_and_exits_to_active() -> None:
    subject = controller()
    subject.on_event(candidate(0))
    assert subject.pending is True

    update = subject.on_event(long_pinch(800))

    assert update.dispatch is None
    assert update.transition is not None
    assert update.transition.accepted is True
    assert update.transition.trigger is TransitionTrigger.LONG_PINCH
    assert update.transition.previous is InteractionState.POINTER_MODE
    assert update.transition.resulting is InteractionState.ACTIVE
    assert subject.pending is False
    assert subject.advance(10_000 * MS) == ClickUpdate()


def test_long_pinch_without_a_pending_click_still_exits_to_active() -> None:
    subject = controller()
    update = subject.on_event(long_pinch(800))
    assert update.transition is not None
    assert update.transition.accepted is True
    assert update.transition.resulting is InteractionState.ACTIVE


def test_a_release_after_long_pinch_dispatches_nothing() -> None:
    subject = controller()
    subject.on_event(candidate(0))
    assert subject.on_event(long_pinch(800)).transition is not None

    # The release that follows the long pinch arrives once the state is ACTIVE.
    release = subject.on_event(candidate(900))
    assert release == ClickUpdate()
    assert subject.pending is False
    assert subject.advance(10_000 * MS) == ClickUpdate()


def test_repeated_long_pinch_events_are_rejected_without_a_click() -> None:
    subject = controller()
    assert subject.on_event(long_pinch(800)).transition is not None

    for timestamp_ms in range(900, 2000, 100):
        update = subject.on_event(long_pinch(timestamp_ms))
        assert update.dispatch is None
        assert update.transition is not None
        assert update.transition.accepted is False
    assert subject.pending is False


def test_a_candidate_in_active_is_ignored() -> None:
    subject = controller(InteractionState.ACTIVE)
    assert subject.on_event(candidate(0)) == ClickUpdate()
    assert subject.pending is False
    assert subject.advance(10_000 * MS) == ClickUpdate()


@pytest.mark.parametrize(
    "state",
    [
        InteractionState.IDLE,
        InteractionState.ACTIVE,
        InteractionState.PAUSED,
        InteractionState.SCROLL_MODE,
        InteractionState.ERROR,
        InteractionState.EXITING,
    ],
)
def test_only_pointer_mode_accepts_a_click_candidate(state: InteractionState) -> None:
    subject = controller(state)
    assert subject.on_event(candidate(0)) == ClickUpdate()
    assert subject.pending is False


def test_entering_pointer_mode_never_seeds_a_click() -> None:
    subject = controller(InteractionState.ACTIVE)
    update = subject.on_event(
        event(GestureAction.ENTER_POINTER_MODE, 100, gesture=Gesture.PINCH)
    )
    assert update == ClickUpdate()
    assert subject.pending is False


def test_cancellation_drops_the_pending_click_and_a_later_release_starts_fresh() -> None:
    subject = controller()
    subject.on_event(candidate(0))
    subject.cancel()

    assert subject.pending is False
    assert subject.advance(10_000 * MS) == ClickUpdate()

    assert subject.on_event(candidate(50)) == ClickUpdate()
    assert subject.pending is True


def test_the_expired_single_click_keeps_its_origin() -> None:
    subject = controller()
    timings = FrameTimings(capture_ts_ns=42)
    subject.on_event(candidate(0), timings=timings)

    update = subject.advance(WINDOW * MS)

    assert update.dispatch is ClickDispatch.SINGLE
    assert update.origin is not None
    assert update.origin.event == candidate(0)
    assert update.origin.timings is timings


def test_a_double_click_keeps_the_first_candidate_origin() -> None:
    subject = controller()
    subject.on_event(candidate(0))

    update = subject.on_event(candidate(200))

    assert update.dispatch is ClickDispatch.DOUBLE
    assert update.origin is not None
    assert update.origin.event == candidate(0)


def test_a_candidate_at_the_deadline_dispatches_the_old_click_and_rearms() -> None:
    subject = controller()
    subject.on_event(candidate(0))

    update = subject.on_event(candidate(WINDOW))

    assert update.dispatch is ClickDispatch.SINGLE
    assert update.origin is not None
    assert update.origin.event == candidate(0)
    assert subject.pending is True

    later = subject.advance(2 * WINDOW * MS)
    assert later.dispatch is ClickDispatch.SINGLE
    assert later.origin is not None
    assert later.origin.event == candidate(WINDOW)
