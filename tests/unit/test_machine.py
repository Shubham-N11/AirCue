from __future__ import annotations

import pytest

from aircue.state.machine import StateMachine
from aircue.state.states import InteractionState
from aircue.state.transitions import (
    TRANSITIONS,
    Termination,
    TransitionTrigger,
    find_transition,
)

S = InteractionState
T = TransitionTrigger


def machine(state: InteractionState = S.INITIALIZING) -> StateMachine:
    return StateMachine(state)


def test_every_listed_row_is_accepted_from_its_source() -> None:
    for row in TRANSITIONS:
        subject = machine(row.source)
        record = subject.apply(row.trigger, 1_000_000)

        assert record.accepted is True
        assert record.previous is row.source
        assert record.trigger is row.trigger
        assert record.reason == row.trigger.value
        assert record.generation == 1
        assert record.timestamp_ns == 1_000_000
        assert subject.generation == 1

        if row.target is Termination.TERMINATED:
            assert record.terminated is True
            assert subject.terminated is True
            assert subject.state is row.source
        else:
            assert record.terminated is False
            assert record.resulting is row.target
            assert subject.state is row.target


def test_every_unlisted_pair_is_rejected_without_a_state_change() -> None:
    for state in InteractionState:
        for trigger in TransitionTrigger:
            listed = find_transition(state, trigger)
            subject = machine(state)
            record = subject.apply(trigger, 1_000_000)

            if listed is not None:
                assert record.accepted is True
                continue

            assert record.accepted is False
            assert record.previous is state
            assert record.resulting is state
            assert subject.state is state
            assert record.generation == 0
            assert subject.generation == 0
            assert record.reason


def test_generation_increments_once_per_accepted_transition() -> None:
    subject = machine()
    steps: list[tuple[TransitionTrigger, InteractionState]] = [
        (T.INITIALIZATION_SUCCEEDED, S.IDLE),
        (T.ACTIVATION_CONFIRMED, S.ACTIVE),
        (T.PINCH_CONFIRMED, S.POINTER_MODE),
        (T.LONG_PINCH, S.ACTIVE),
        (T.FIST_CONFIRMED, S.PAUSED),
        (T.RESUME_CONFIRMED, S.ACTIVE),
        (T.EXIT_REQUEST, S.EXITING),
    ]
    for expected_generation, (trigger, expected_state) in enumerate(steps, start=1):
        record = subject.apply(trigger, expected_generation * 1_000_000)
        assert record.accepted is True
        assert record.generation == expected_generation
        assert record.timestamp_ns == expected_generation * 1_000_000
        assert subject.state is expected_state
        assert subject.generation == expected_generation

    terminated = subject.apply(T.CLEANUP_COMPLETED, 8_000_000)
    assert terminated.accepted is True
    assert terminated.terminated is True
    assert terminated.generation == 8
    assert subject.terminated is True


def test_rejection_does_not_advance_the_generation_or_timestamp() -> None:
    subject = machine()
    accepted = subject.apply(T.INITIALIZATION_SUCCEEDED, 5_000_000)
    assert accepted.accepted is True

    rejected = subject.apply(T.PINCH_CONFIRMED, 6_000_000)
    assert rejected.accepted is False
    assert rejected.generation == accepted.generation
    assert subject.state is S.IDLE
    assert subject.generation == 1

    # The rejected timestamp must not become the monotonic baseline.
    follow_up = subject.apply(T.ACTIVATION_CONFIRMED, 5_500_000)
    assert follow_up.accepted is True
    assert follow_up.generation == 2


def test_non_monotonic_timestamp_is_rejected() -> None:
    subject = machine()
    assert subject.apply(T.INITIALIZATION_SUCCEEDED, 2_000_000).accepted is True

    record = subject.apply(T.ACTIVATION_CONFIRMED, 1_999_999)
    assert record.accepted is False
    assert record.reason == "timestamp is older than the last applied transition"
    assert subject.state is S.IDLE
    assert subject.generation == 1

    assert subject.apply(T.ACTIVATION_CONFIRMED, 2_000_000).accepted is True
    assert subject.state is S.ACTIVE


def test_noop_row_is_accepted_and_increments_the_generation() -> None:
    subject = machine(S.IDLE)
    record = subject.apply(T.TRACKING_LOSS, 1_000_000)
    assert record.accepted is True
    assert record.resulting is S.IDLE
    assert subject.state is S.IDLE
    assert subject.generation == 1


def test_custom_reason_overrides_the_trigger_value() -> None:
    subject = machine()
    record = subject.apply(
        T.INITIALIZATION_SUCCEEDED, 1_000_000, reason="camera and adapter ready"
    )
    assert record.reason == "camera and adapter ready"


def test_terminated_machine_rejects_every_trigger() -> None:
    subject = machine(S.EXITING)
    assert subject.apply(T.CLEANUP_COMPLETED, 1_000_000).terminated is True

    for trigger in TransitionTrigger:
        record = subject.apply(trigger, 2_000_000)
        assert record.accepted is False
        assert record.reason == "runtime already terminated"
        assert subject.generation == 1
        assert subject.terminated is True


def test_cleanup_completed_cannot_run_twice() -> None:
    subject = machine(S.EXITING)
    assert subject.apply(T.CLEANUP_COMPLETED, 1_000_000).accepted is True
    second = subject.apply(T.CLEANUP_COMPLETED, 2_000_000)
    assert second.accepted is False
    assert second.terminated is False
    assert subject.generation == 1


@pytest.mark.parametrize("state", list(InteractionState))
def test_initial_state_can_be_injected(state: InteractionState) -> None:
    assert machine().state is S.INITIALIZING
    assert machine(state).state is state
