"""The transition table matches design.md D3.1 exactly, row for row."""

from __future__ import annotations

import pytest

from aircue.state.states import InteractionState
from aircue.state.transitions import (
    TRANSITIONS,
    Termination,
    TransitionTrigger,
    find_transition,
)

S = InteractionState
T = TransitionTrigger

# Transcribed independently from the design.md D3.1 table.
EXPECTED_ROWS: tuple[tuple[InteractionState, TransitionTrigger, object], ...] = (
    (S.INITIALIZING, T.INITIALIZATION_SUCCEEDED, S.IDLE),
    (S.INITIALIZING, T.INITIALIZATION_FAILED, S.ERROR),
    (S.INITIALIZING, T.EXIT_REQUEST, S.EXITING),
    (S.IDLE, T.ACTIVATION_CONFIRMED, S.ACTIVE),
    (S.IDLE, T.TRACKING_LOSS, S.IDLE),
    (S.IDLE, T.FOCUS_LOSS, S.IDLE),
    (S.IDLE, T.DEACTIVATION_HOTKEY, S.IDLE),
    (S.IDLE, T.EXIT_REQUEST, S.EXITING),
    (S.IDLE, T.UNRECOVERABLE_FAULT, S.ERROR),
    (S.ACTIVE, T.FIST_CONFIRMED, S.PAUSED),
    (S.ACTIVE, T.PINCH_CONFIRMED, S.POINTER_MODE),
    (S.ACTIVE, T.PEACE_CONFIRMED, S.SCROLL_MODE),
    (S.ACTIVE, T.TRACKING_TIMEOUT, S.IDLE),
    (S.ACTIVE, T.FOCUS_LOSS, S.PAUSED),
    (S.ACTIVE, T.RECOVERABLE_ADAPTER_ERROR, S.PAUSED),
    (S.ACTIVE, T.UNRECOVERABLE_ADAPTER_ERROR, S.ERROR),
    (S.ACTIVE, T.CAMERA_FAULT, S.ERROR),
    (S.ACTIVE, T.UNRECOVERABLE_INTERNAL_FAULT, S.ERROR),
    (S.ACTIVE, T.DEACTIVATION_HOTKEY, S.IDLE),
    (S.ACTIVE, T.EXIT_REQUEST, S.EXITING),
    (S.PAUSED, T.RESUME_CONFIRMED, S.ACTIVE),
    (S.PAUSED, T.TRACKING_TIMEOUT, S.IDLE),
    (S.PAUSED, T.DEACTIVATION_HOTKEY, S.IDLE),
    (S.PAUSED, T.EXIT_REQUEST, S.EXITING),
    (S.PAUSED, T.UNRECOVERABLE_FAULT, S.ERROR),
    (S.POINTER_MODE, T.LONG_PINCH, S.ACTIVE),
    (S.POINTER_MODE, T.FIST_CONFIRMED, S.PAUSED),
    (S.POINTER_MODE, T.FOCUS_LOSS, S.PAUSED),
    (S.POINTER_MODE, T.TRACKING_TIMEOUT, S.IDLE),
    (S.POINTER_MODE, T.RECOVERABLE_ADAPTER_ERROR, S.PAUSED),
    (S.POINTER_MODE, T.UNRECOVERABLE_ADAPTER_ERROR, S.ERROR),
    (S.POINTER_MODE, T.CAMERA_FAULT, S.ERROR),
    (S.POINTER_MODE, T.UNRECOVERABLE_INTERNAL_FAULT, S.ERROR),
    (S.POINTER_MODE, T.DEACTIVATION_HOTKEY, S.IDLE),
    (S.POINTER_MODE, T.EXIT_REQUEST, S.EXITING),
    (S.SCROLL_MODE, T.PEACE_CONFIRMED, S.ACTIVE),
    (S.SCROLL_MODE, T.FIST_CONFIRMED, S.PAUSED),
    (S.SCROLL_MODE, T.FOCUS_LOSS, S.PAUSED),
    (S.SCROLL_MODE, T.TRACKING_TIMEOUT, S.IDLE),
    (S.SCROLL_MODE, T.RECOVERABLE_ADAPTER_ERROR, S.PAUSED),
    (S.SCROLL_MODE, T.UNRECOVERABLE_ADAPTER_ERROR, S.ERROR),
    (S.SCROLL_MODE, T.CAMERA_FAULT, S.ERROR),
    (S.SCROLL_MODE, T.UNRECOVERABLE_INTERNAL_FAULT, S.ERROR),
    (S.SCROLL_MODE, T.DEACTIVATION_HOTKEY, S.IDLE),
    (S.SCROLL_MODE, T.EXIT_REQUEST, S.EXITING),
    (S.ERROR, T.REINITIALIZATION_SUCCEEDED, S.IDLE),
    (S.ERROR, T.CAMERA_RECONNECT_SUCCEEDED, S.IDLE),
    (S.ERROR, T.EXIT_REQUEST, S.EXITING),
    (S.EXITING, T.CLEANUP_COMPLETED, Termination.TERMINATED),
)


def test_table_has_the_exact_expected_rows() -> None:
    actual = {(row.source, row.trigger, row.target) for row in TRANSITIONS}
    assert actual == set(EXPECTED_ROWS)
    assert len(TRANSITIONS) == len(EXPECTED_ROWS)


def test_no_duplicate_source_trigger_pairs() -> None:
    keys = [(row.source, row.trigger) for row in TRANSITIONS]
    assert len(set(keys)) == len(keys)


def test_every_listed_pair_resolves() -> None:
    for source, trigger, target in EXPECTED_ROWS:
        transition = find_transition(source, trigger)
        assert transition is not None
        assert transition.target is target


def test_every_unlisted_pair_is_rejected() -> None:
    listed = {(source, trigger) for source, trigger, _ in EXPECTED_ROWS}
    unlisted = [
        (state, trigger)
        for state in InteractionState
        for trigger in TransitionTrigger
        if (state, trigger) not in listed
    ]
    assert len(unlisted) == len(InteractionState) * len(TransitionTrigger) - len(listed)
    for state, trigger in unlisted:
        assert find_transition(state, trigger) is None


def test_noop_rows_are_recognised_without_a_state_change() -> None:
    for state, trigger, target in EXPECTED_ROWS:
        transition = find_transition(state, trigger)
        assert transition is not None
        assert transition.changes_state is (target is not state)


@pytest.mark.parametrize(
    ("source", "trigger"),
    [
        (S.IDLE, T.PINCH_CONFIRMED),
        (S.IDLE, T.PEACE_CONFIRMED),
        (S.IDLE, T.FIST_CONFIRMED),
        (S.ACTIVE, T.RESUME_CONFIRMED),
        (S.PAUSED, T.PINCH_CONFIRMED),
        (S.PAUSED, T.PEACE_CONFIRMED),
        (S.POINTER_MODE, T.PEACE_CONFIRMED),
        (S.SCROLL_MODE, T.PINCH_CONFIRMED),
        (S.ERROR, T.ACTIVATION_CONFIRMED),
        (S.ERROR, T.PINCH_CONFIRMED),
        (S.EXITING, T.EXIT_REQUEST),
        (S.EXITING, T.DEACTIVATION_HOTKEY),
    ],
)
def test_forbidden_pairs_are_not_permitted(
    source: InteractionState, trigger: TransitionTrigger
) -> None:
    assert find_transition(source, trigger) is None


def test_mode_entry_only_from_active() -> None:
    entries = {TransitionTrigger.PINCH_CONFIRMED, TransitionTrigger.PEACE_CONFIRMED}
    for transition in TRANSITIONS:
        if transition.trigger in entries and transition.target in {
            S.POINTER_MODE,
            S.SCROLL_MODE,
        }:
            assert transition.source is S.ACTIVE


def test_no_direct_switch_between_pointer_and_scroll_modes() -> None:
    for transition in TRANSITIONS:
        assert not (transition.source is S.POINTER_MODE and transition.target is S.SCROLL_MODE)
        assert not (transition.source is S.SCROLL_MODE and transition.target is S.POINTER_MODE)


def test_no_automatic_activation_from_idle() -> None:
    for transition in TRANSITIONS:
        if transition.source is S.IDLE and transition.target is S.ACTIVE:
            assert transition.trigger is TransitionTrigger.ACTIVATION_CONFIRMED


def test_exiting_only_terminates() -> None:
    exits = [row for row in TRANSITIONS if row.source is S.EXITING]
    assert len(exits) == 1
    assert exits[0].trigger is TransitionTrigger.CLEANUP_COMPLETED
    assert exits[0].target is Termination.TERMINATED


def test_interaction_state_has_exactly_eight_members() -> None:
    assert set(InteractionState) == {
        S.INITIALIZING,
        S.IDLE,
        S.ACTIVE,
        S.PAUSED,
        S.POINTER_MODE,
        S.SCROLL_MODE,
        S.ERROR,
        S.EXITING,
    }
