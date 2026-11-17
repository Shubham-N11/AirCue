from __future__ import annotations

import pytest

from aircue.commands.click import ClickArbiter, ClickDispatch
from aircue.commands.manager import CommandManager
from aircue.commands.pointer import PointerRejection, check_pointer_movement
from aircue.presentation.target import TargetKind, capabilities_for
from aircue.state.states import InteractionState

MS = 1_000_000
WINDOW = 350


def test_one_candidate_waits_for_the_window() -> None:
    arbiter = ClickArbiter()
    assert arbiter.candidate(0) is None
    assert arbiter.pending is True


def test_the_window_expires_into_one_single_click() -> None:
    arbiter = ClickArbiter()
    arbiter.candidate(0)

    assert arbiter.advance((WINDOW - 1) * MS) is None
    assert arbiter.advance(WINDOW * MS) is ClickDispatch.SINGLE
    assert arbiter.pending is False
    assert arbiter.advance(10_000 * MS) is None


def test_a_second_candidate_inside_the_window_is_one_double_click() -> None:
    arbiter = ClickArbiter()
    arbiter.candidate(0)

    assert arbiter.candidate(200 * MS) is ClickDispatch.DOUBLE
    assert arbiter.pending is False
    assert arbiter.advance(10_000 * MS) is None


def test_a_candidate_at_the_deadline_starts_a_new_window() -> None:
    arbiter = ClickArbiter()
    arbiter.candidate(0)

    assert arbiter.candidate(WINDOW * MS) is ClickDispatch.SINGLE
    assert arbiter.pending is True
    assert arbiter.advance(WINDOW * 2 * MS) is ClickDispatch.SINGLE


def test_a_third_candidate_after_a_double_click_starts_again() -> None:
    arbiter = ClickArbiter()
    arbiter.candidate(0)
    assert arbiter.candidate(100 * MS) is ClickDispatch.DOUBLE
    assert arbiter.pending is False

    assert arbiter.candidate(500 * MS) is None
    assert arbiter.pending is True
    assert arbiter.advance(500 * MS + WINDOW * MS) is ClickDispatch.SINGLE


@pytest.mark.parametrize(
    "event",
    [
        "tracking loss",
        "pointer invalidity",
        "focus loss",
        "state change",
        "mode change",
        "long pinch",
        "target loss",
    ],
)
def test_each_cancellation_event_drops_the_click_without_dispatch(event: str) -> None:
    arbiter = ClickArbiter()
    arbiter.candidate(0)
    assert arbiter.pending is True

    arbiter.cancel()

    assert arbiter.pending is False
    assert arbiter.advance(10_000 * MS) is None


def test_cancelling_without_a_pending_click_is_a_no_op() -> None:
    arbiter = ClickArbiter()
    arbiter.cancel()
    assert arbiter.pending is False
    assert arbiter.advance(0) is None


def test_a_pending_click_freezes_pointer_movement() -> None:
    arbiter = ClickArbiter()
    arbiter.candidate(0)

    decision = check_pointer_movement(
        CommandManager(),
        InteractionState.POINTER_MODE,
        capabilities_for(TargetKind.NORMAL_SLIDESHOW),
        pointer_valid=True,
        pinch_closed=False,
        click_pending=arbiter.pending,
    )
    assert decision.rejection is PointerRejection.PENDING_CLICK


def test_the_window_must_be_positive() -> None:
    with pytest.raises(ValueError):
        ClickArbiter(double_click_window_ms=0)
