from __future__ import annotations

import pytest

from aircue.commands.manager import CommandManager
from aircue.commands.pointer import (
    PointerDecision,
    PointerRejection,
    check_pointer_movement,
)
from aircue.presentation.target import TargetKind, capabilities_for
from aircue.state.states import InteractionState

S = InteractionState
MANAGER = CommandManager()
POINTER = capabilities_for(TargetKind.NORMAL_SLIDESHOW)
NAVIGATION_ONLY = capabilities_for(TargetKind.PRESENTER_VIEW)
NO_CAPABILITIES = capabilities_for(TargetKind.EDIT_MODE)


def check(
    state: InteractionState = S.POINTER_MODE,
    capabilities=POINTER,
    *,
    pointer_valid: bool = True,
    pinch_closed: bool = False,
    click_pending: bool = False,
) -> PointerDecision:
    return check_pointer_movement(
        MANAGER,
        state,
        capabilities,
        pointer_valid=pointer_valid,
        pinch_closed=pinch_closed,
        click_pending=click_pending,
    )


def test_a_valid_sample_in_pointer_mode_is_allowed() -> None:
    assert check() == PointerDecision()
    assert check().allowed is True


@pytest.mark.parametrize("state", [state for state in S if state is not S.POINTER_MODE])
def test_every_other_state_rejects_pointer_movement(state: InteractionState) -> None:
    decision = check(state)
    assert decision.allowed is False
    assert decision.rejection is PointerRejection.STATE
    assert state.value in decision.reason


def test_scroll_mode_cannot_emit_pointer_movement() -> None:
    decision = check(S.SCROLL_MODE)
    assert decision.rejection is PointerRejection.STATE


def test_active_mode_cannot_emit_pointer_movement() -> None:
    decision = check(S.ACTIVE)
    assert decision.rejection is PointerRejection.STATE


def test_a_navigation_only_target_rejects_pointer_movement() -> None:
    decision = check(capabilities=NAVIGATION_ONLY)
    assert decision.rejection is PointerRejection.CAPABILITY
    assert "pointer" in decision.reason


@pytest.mark.parametrize("kind", [TargetKind.EDIT_MODE, TargetKind.UNKNOWN])
def test_a_target_without_capabilities_rejects_pointer_movement(
    kind: TargetKind,
) -> None:
    decision = check(capabilities=capabilities_for(kind))
    assert decision.rejection is PointerRejection.CAPABILITY


def test_an_invalid_pose_rejects_pointer_movement() -> None:
    decision = check(pointer_valid=False)
    assert decision.rejection is PointerRejection.POSE


def test_a_closed_pinch_rejects_pointer_movement() -> None:
    decision = check(pinch_closed=True)
    assert decision.rejection is PointerRejection.CLOSED_PINCH


def test_a_pending_click_freezes_pointer_movement() -> None:
    decision = check(click_pending=True)
    assert decision.rejection is PointerRejection.PENDING_CLICK


def test_state_and_capability_are_checked_before_pointer_conditions() -> None:
    decision = check(
        S.ACTIVE,
        NO_CAPABILITIES,
        pointer_valid=False,
        pinch_closed=True,
        click_pending=True,
    )
    assert decision.rejection is PointerRejection.STATE


def test_the_pose_is_checked_before_pinch_and_pending_click() -> None:
    decision = check(pointer_valid=False, pinch_closed=True, click_pending=True)
    assert decision.rejection is PointerRejection.POSE


def test_pointer_movement_alone_cannot_click_change_mode_or_scroll() -> None:
    # The only accepted state is POINTER_MODE, the click window blocks moves,
    # and the scroll mode is rejected: this path has no other output.
    assert check().allowed is True
    assert check(click_pending=True).rejection is PointerRejection.PENDING_CLICK
    assert check(S.SCROLL_MODE).rejection is PointerRejection.STATE
    assert check(S.ACTIVE).rejection is PointerRejection.STATE
