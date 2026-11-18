from __future__ import annotations

import pytest

from aircue.commands.click import (
    ClickDecision,
    ClickDispatch,
    ClickRejection,
    gate_click,
)
from aircue.commands.commands import Command
from aircue.commands.manager import CommandManager
from aircue.presentation.adapter import Click, DoubleClick
from aircue.presentation.target import TargetKind, capabilities_for
from aircue.state.states import InteractionState

S = InteractionState
MANAGER = CommandManager()
POINTER = capabilities_for(TargetKind.NORMAL_SLIDESHOW)


def gate(
    dispatch: ClickDispatch = ClickDispatch.SINGLE,
    *,
    state: InteractionState = S.POINTER_MODE,
    capabilities=POINTER,
    foreground: bool = True,
) -> ClickDecision:
    return gate_click(
        MANAGER,
        dispatch,
        state,
        capabilities,
        foreground=foreground,
    )


def test_a_single_click_in_pointer_mode_becomes_a_click_payload() -> None:
    decision = gate()
    assert decision == ClickDecision(
        command=Command.CLICK,
        state=S.POINTER_MODE,
        payload=Click(),
    )
    assert decision.allowed is True


def test_a_double_click_in_pointer_mode_becomes_a_double_click_payload() -> None:
    decision = gate(ClickDispatch.DOUBLE)
    assert decision.command is Command.DOUBLE_CLICK
    assert decision.payload == DoubleClick()
    assert decision.allowed is True


def test_presenter_view_records_a_capability_rejection_without_input() -> None:
    for dispatch in ClickDispatch:
        decision = gate(dispatch, capabilities=capabilities_for(TargetKind.PRESENTER_VIEW))
        assert decision.rejection is ClickRejection.CAPABILITY
        assert decision.payload is None
        assert "pointer" in decision.reason


@pytest.mark.parametrize("kind", [TargetKind.EDIT_MODE, TargetKind.UNKNOWN])
def test_a_target_without_pointer_capability_rejects_both_clicks(kind: TargetKind) -> None:
    for dispatch in ClickDispatch:
        decision = gate(dispatch, capabilities=capabilities_for(kind))
        assert decision.rejection is ClickRejection.CAPABILITY
        assert decision.payload is None
        assert "pointer" in decision.reason


def test_clicking_without_foreground_focus_records_a_focus_rejection() -> None:
    for dispatch in ClickDispatch:
        decision = gate(dispatch, foreground=False)
        assert decision.rejection is ClickRejection.FOCUS
        assert decision.payload is None
        assert "foreground" in decision.reason


@pytest.mark.parametrize(
    "state",
    [
        InteractionState.INITIALIZING,
        InteractionState.IDLE,
        InteractionState.ACTIVE,
        InteractionState.PAUSED,
        InteractionState.SCROLL_MODE,
        InteractionState.ERROR,
        InteractionState.EXITING,
    ],
)
def test_only_pointer_mode_allows_a_click(state: InteractionState) -> None:
    for dispatch in ClickDispatch:
        decision = gate(dispatch, state=state)
        assert decision.rejection is ClickRejection.STATE
        assert decision.payload is None
        assert state.value in decision.reason


def test_state_is_checked_before_capability_and_focus() -> None:
    decision = gate(
        state=S.ACTIVE,
        capabilities=capabilities_for(TargetKind.PRESENTER_VIEW),
        foreground=False,
    )
    assert decision.rejection is ClickRejection.STATE


def test_capability_is_checked_before_focus() -> None:
    decision = gate(
        capabilities=capabilities_for(TargetKind.PRESENTER_VIEW),
        foreground=False,
    )
    assert decision.rejection is ClickRejection.CAPABILITY


def test_a_rejected_click_has_no_payload_for_any_reason() -> None:
    rejections = [
        gate(state=S.ACTIVE),
        gate(capabilities=capabilities_for(TargetKind.PRESENTER_VIEW)),
        gate(foreground=False),
    ]
    assert all(not decision.allowed for decision in rejections)
    assert all(decision.payload is None for decision in rejections)
