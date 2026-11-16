from __future__ import annotations

import pytest

from aircue.commands.commands import Command, CommandDecision, CommandRejection
from aircue.commands.manager import CommandManager
from aircue.commands.priority import PRIORITY, highest_priority, priority_rank
from aircue.presentation.target import TargetCapabilities, TargetKind, capabilities_for
from aircue.state.states import InteractionState

S = InteractionState
C = Command
FULL = capabilities_for(TargetKind.NORMAL_SLIDESHOW)
PRESENTER = capabilities_for(TargetKind.PRESENTER_VIEW)
NONE = TargetCapabilities()
ALL_STATES = list(InteractionState)
ALL_COMMANDS = list(Command)

# The state-only gate, transcribed from the specs and design.md D3.
ALLOWED_STATES: dict[Command, frozenset[InteractionState]] = {
    C.EXIT: frozenset(set(S) - {S.EXITING}),
    C.PAUSE: frozenset({S.ACTIVE, S.POINTER_MODE, S.SCROLL_MODE}),
    C.RESUME: frozenset({S.PAUSED}),
    C.ACTIVATE: frozenset({S.IDLE}),
    C.ENTER_POINTER_MODE: frozenset({S.ACTIVE}),
    C.EXIT_POINTER_MODE: frozenset({S.POINTER_MODE}),
    C.ENTER_SCROLL_MODE: frozenset({S.ACTIVE}),
    C.EXIT_SCROLL_MODE: frozenset({S.SCROLL_MODE}),
    C.NEXT_SLIDE: frozenset({S.ACTIVE}),
    C.PREVIOUS_SLIDE: frozenset({S.ACTIVE}),
    C.CLICK: frozenset({S.POINTER_MODE}),
    C.DOUBLE_CLICK: frozenset({S.POINTER_MODE}),
    C.SCROLL: frozenset({S.SCROLL_MODE}),
    C.POINTER_MOVE: frozenset({S.POINTER_MODE}),
}

POINTER_COMMANDS = (
    C.ENTER_POINTER_MODE,
    C.ENTER_SCROLL_MODE,
    C.CLICK,
    C.DOUBLE_CLICK,
    C.SCROLL,
    C.POINTER_MOVE,
)
POINTER_OUTPUT_COMMANDS = (C.CLICK, C.DOUBLE_CLICK, C.SCROLL, C.POINTER_MOVE)
NAVIGATION_COMMANDS = (C.NEXT_SLIDE, C.PREVIOUS_SLIDE)


def manager() -> CommandManager:
    return CommandManager()


@pytest.mark.parametrize(("command", "state"), [(c, s) for c in ALL_COMMANDS for s in ALL_STATES])
def test_every_state_command_pair_matches_the_gate(
    command: Command, state: InteractionState
) -> None:
    decision = manager().validate(command, state, FULL)
    expected = state in ALLOWED_STATES[command]
    assert decision.allowed is expected
    if expected:
        assert decision.rejection is None
    else:
        assert decision.rejection is CommandRejection.STATE


def test_the_state_gate_covers_every_command() -> None:
    assert set(ALLOWED_STATES) == set(Command)


def test_pointer_commands_are_rejected_in_active() -> None:
    for command in POINTER_OUTPUT_COMMANDS:
        decision = manager().validate(command, S.ACTIVE, FULL)
        assert decision.allowed is False
        assert decision.rejection is CommandRejection.STATE
        assert decision.reason


def test_slide_commands_are_rejected_while_paused() -> None:
    for command in NAVIGATION_COMMANDS:
        decision = manager().validate(command, S.PAUSED, FULL)
        assert decision.allowed is False
        assert decision.rejection is CommandRejection.STATE


def test_navigation_is_rejected_outside_active() -> None:
    for command in NAVIGATION_COMMANDS:
        for state in ALL_STATES:
            if state is S.ACTIVE:
                continue
            assert manager().validate(command, state, PRESENTER).allowed is False


def test_presenter_view_allows_navigation() -> None:
    for command in NAVIGATION_COMMANDS:
        decision = manager().validate(command, S.ACTIVE, PRESENTER)
        assert decision.allowed is True
        assert decision.command is command


def test_presenter_view_rejects_pointer_commands() -> None:
    for command in POINTER_COMMANDS:
        state = next(iter(ALLOWED_STATES[command]))
        decision = manager().validate(command, state, PRESENTER)
        assert decision.allowed is False
        assert decision.rejection is CommandRejection.CAPABILITY
        assert "pointer" in decision.reason


@pytest.mark.parametrize("kind", [TargetKind.EDIT_MODE, TargetKind.UNKNOWN])
def test_degraded_targets_reject_navigation_and_pointer(kind: TargetKind) -> None:
    capabilities = capabilities_for(kind)
    for command in NAVIGATION_COMMANDS + POINTER_COMMANDS:
        state = next(iter(ALLOWED_STATES[command]))
        decision = manager().validate(command, state, capabilities)
        assert decision.allowed is False
        assert decision.rejection is CommandRejection.CAPABILITY


def test_mode_exits_need_no_capability() -> None:
    assert manager().validate(C.EXIT_POINTER_MODE, S.POINTER_MODE, NONE).allowed is True
    assert manager().validate(C.EXIT_SCROLL_MODE, S.SCROLL_MODE, NONE).allowed is True


def test_control_commands_need_no_capability() -> None:
    assert manager().validate(C.EXIT, S.ACTIVE, NONE).allowed is True
    assert manager().validate(C.PAUSE, S.ACTIVE, NONE).allowed is True
    assert manager().validate(C.RESUME, S.PAUSED, NONE).allowed is True
    assert manager().validate(C.ACTIVATE, S.IDLE, NONE).allowed is True


def test_exit_is_rejected_only_in_exiting() -> None:
    for state in ALL_STATES:
        expected = state is not S.EXITING
        assert manager().validate(C.EXIT, state, FULL).allowed is expected


def test_priority_groups_match_the_specified_order() -> None:
    assert PRIORITY == (
        (C.EXIT,),
        (C.PAUSE,),
        (C.RESUME, C.ACTIVATE),
        (C.EXIT_SCROLL_MODE, C.EXIT_POINTER_MODE),
        (C.ENTER_SCROLL_MODE, C.ENTER_POINTER_MODE),
        (C.NEXT_SLIDE, C.PREVIOUS_SLIDE),
        (C.CLICK, C.DOUBLE_CLICK),
        (C.SCROLL,),
        (C.POINTER_MOVE,),
    )


def test_every_command_has_a_distinct_rank() -> None:
    ranks = [priority_rank(command) for command in Command]
    assert len(set(ranks)) == len(ranks)


def test_exit_outranks_every_other_command() -> None:
    others = [command for command in Command if command is not C.EXIT]
    for other in others:
        assert priority_rank(C.EXIT) < priority_rank(other)
        assert highest_priority([other, C.EXIT]) is C.EXIT


def test_priority_resolution_is_order_independent() -> None:
    batch = [C.POINTER_MOVE, C.SCROLL, C.CLICK, C.NEXT_SLIDE, C.PAUSE]
    assert highest_priority(batch) is C.PAUSE
    assert highest_priority(reversed(batch)) is C.PAUSE


def test_highest_priority_of_nothing_is_none() -> None:
    assert highest_priority([]) is None


def test_select_with_no_candidates_returns_none() -> None:
    assert manager().select([], S.ACTIVE, FULL) is None


def test_select_returns_the_allowed_top_command() -> None:
    decision = manager().select([C.POINTER_MOVE, C.NEXT_SLIDE], S.ACTIVE, FULL)
    assert decision is not None
    assert decision.command is C.NEXT_SLIDE
    assert decision.allowed is True


def test_select_returns_the_rejection_when_the_top_command_is_gated() -> None:
    decision = manager().select([C.RESUME, C.NEXT_SLIDE], S.ACTIVE, FULL)
    assert decision is not None
    assert decision.command is C.RESUME
    assert decision.allowed is False
    assert decision.rejection is CommandRejection.STATE


def test_select_does_not_fall_through_to_a_lower_priority_command() -> None:
    decision = manager().select([C.SCROLL, C.POINTER_MOVE], S.POINTER_MODE, FULL)
    assert isinstance(decision, CommandDecision)
    assert decision.command is C.SCROLL
    assert decision.allowed is False


def test_select_honours_capabilities() -> None:
    decision = manager().select([C.NEXT_SLIDE], S.ACTIVE, PRESENTER)
    assert decision is not None
    assert decision.allowed is True

    decision = manager().select([C.NEXT_SLIDE], S.ACTIVE, NONE)
    assert decision is not None
    assert decision.rejection is CommandRejection.CAPABILITY


def test_decision_records_the_command_and_state() -> None:
    decision = manager().validate(C.NEXT_SLIDE, S.ACTIVE, FULL)
    assert decision.command is C.NEXT_SLIDE
    assert decision.state is S.ACTIVE
    assert decision.reason == ""
