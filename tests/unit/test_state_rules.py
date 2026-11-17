from __future__ import annotations

import pytest

from aircue.commands.commands import Command, CommandRejection
from aircue.commands.manager import CommandManager
from aircue.presentation.target import TargetKind, capabilities_for
from aircue.state.machine import StateMachine
from aircue.state.states import InteractionState
from aircue.state.transitions import TRANSITIONS, TransitionTrigger

S = InteractionState
T = TransitionTrigger
C = Command
FULL = capabilities_for(TargetKind.NORMAL_SLIDESHOW)
MODE_STATES = (S.POINTER_MODE, S.SCROLL_MODE)


def test_paused_resumes_only_to_active() -> None:
    for trigger in TransitionTrigger:
        record = StateMachine(S.PAUSED).apply(trigger, 0)
        if record.accepted and record.resulting is S.ACTIVE:
            assert trigger is T.RESUME_CONFIRMED
        assert record.resulting is not S.POINTER_MODE
        assert record.resulting is not S.SCROLL_MODE


def test_modes_are_entered_only_from_active() -> None:
    for row in TRANSITIONS:
        if row.target in MODE_STATES:
            assert row.source is S.ACTIVE


def test_modes_exit_only_to_active_or_a_safety_state() -> None:
    allowed = {S.ACTIVE, S.PAUSED, S.IDLE, S.ERROR, S.EXITING}
    for row in TRANSITIONS:
        if row.source in MODE_STATES:
            assert row.target in allowed


@pytest.mark.parametrize(
    ("source", "entry", "switch_trigger"),
    [
        (S.POINTER_MODE, C.ENTER_SCROLL_MODE, T.PEACE_CONFIRMED),
        (S.SCROLL_MODE, C.ENTER_POINTER_MODE, T.PINCH_CONFIRMED),
    ],
)
def test_direct_mode_switches_are_rejected_and_recorded(
    source: InteractionState, entry: Command, switch_trigger: TransitionTrigger
) -> None:
    decision = CommandManager().validate(entry, source, FULL)
    assert decision.allowed is False
    assert decision.rejection is CommandRejection.STATE
    assert decision.reason

    machine = StateMachine(source)
    record = machine.apply(switch_trigger, 0)
    assert record.accepted is False
    assert record.previous is source
    assert record.resulting is source
    assert record.reason
    assert machine.state is source
    assert machine.generation == 0


def test_exiting_accepts_no_command() -> None:
    for command in Command:
        decision = CommandManager().validate(command, S.EXITING, FULL)
        assert decision.allowed is False
        assert decision.rejection is CommandRejection.STATE


def test_exiting_accepts_no_transition_except_cleanup() -> None:
    for trigger in TransitionTrigger:
        machine = StateMachine(S.EXITING)
        record = machine.apply(trigger, 0)
        if trigger is T.CLEANUP_COMPLETED:
            assert record.accepted is True
            assert record.terminated is True
        else:
            assert record.accepted is False
            assert machine.state is S.EXITING
            assert machine.generation == 0
