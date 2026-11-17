from __future__ import annotations

import pytest

from aircue.commands.commands import Command, CommandRejection
from aircue.commands.manager import CommandManager
from aircue.presentation.target import TargetKind, capabilities_for
from aircue.state.machine import StateMachine
from aircue.state.recovery import RecoveryController
from aircue.state.states import InteractionState
from aircue.state.transitions import TRANSITIONS, TransitionTrigger

S = InteractionState
T = TransitionTrigger


def controller(
    initial: InteractionState = S.INITIALIZING, **overrides
) -> tuple[StateMachine, RecoveryController]:
    settings = {"reconnect_attempts": 3, "reconnect_backoff_ms": 500}
    settings.update(overrides)
    machine = StateMachine(initial)
    return machine, RecoveryController(machine, **settings)


@pytest.mark.parametrize(
    ("source", "trigger"),
    [(row.source, row.trigger) for row in TRANSITIONS if row.target is S.ERROR],
)
def test_each_unrecoverable_fault_enters_error(
    source: InteractionState, trigger: TransitionTrigger
) -> None:
    machine, subject = controller(source)
    record = subject.fault(trigger, 0)
    assert record.accepted is True
    assert machine.state is S.ERROR
    assert subject.error_cause is trigger


def test_rejected_fault_leaves_the_error_cause_unset() -> None:
    machine, subject = controller(S.IDLE)
    record = subject.fault(T.CAMERA_FAULT, 0)
    assert record.accepted is False
    assert machine.state is S.IDLE
    assert subject.error_cause is None


def test_no_error_state_reaches_active() -> None:
    for trigger in TransitionTrigger:
        machine, _ = controller(S.ERROR)
        record = machine.apply(trigger, 0)
        if record.accepted:
            assert record.resulting is not S.ACTIVE
            assert record.resulting in (S.IDLE, S.EXITING)


def test_explicit_reinitialization_recovers_any_error_to_idle() -> None:
    machine, subject = controller(S.ACTIVE)
    subject.fault(T.UNRECOVERABLE_ADAPTER_ERROR, 0)
    record = subject.reinitialize(1)
    assert record.accepted is True
    assert machine.state is S.IDLE
    assert subject.error_cause is None


def test_camera_fault_recovers_through_a_bounded_reconnect() -> None:
    machine, subject = controller(S.POINTER_MODE)
    subject.fault(T.CAMERA_FAULT, 0)
    assert subject.reconnect_attempts_left == 3
    assert subject.camera_attempt_failed() == 2

    record = subject.camera_reconnected(1)
    assert record.accepted is True
    assert machine.state is S.IDLE
    assert subject.error_cause is None
    assert subject.reconnect_attempts_left == 0


def test_adapter_error_cannot_be_cleared_by_camera_reconnect() -> None:
    machine, subject = controller(S.ACTIVE)
    subject.fault(T.UNRECOVERABLE_ADAPTER_ERROR, 0)

    record = subject.camera_reconnected(1)
    assert record.accepted is False
    assert record.generation == machine.generation
    assert "adapter" in record.reason
    assert machine.state is S.ERROR

    assert subject.reinitialize(2).accepted is True
    assert machine.state is S.IDLE


def test_camera_reconnect_is_rejected_after_three_failures() -> None:
    machine, subject = controller(S.SCROLL_MODE)
    subject.fault(T.CAMERA_FAULT, 0)
    assert [subject.camera_attempt_failed() for _ in range(3)] == [2, 1, 0]

    record = subject.camera_reconnected(1)
    assert record.accepted is False
    assert "exhausted" in record.reason
    assert machine.state is S.ERROR

    assert subject.reinitialize(2).accepted is True
    assert machine.state is S.IDLE


def test_reconnect_budget_is_configurable() -> None:
    _, subject = controller(S.ACTIVE, reconnect_attempts=1, reconnect_backoff_ms=250)
    assert subject.reconnect_backoff_ns == 250_000_000
    subject.fault(T.CAMERA_FAULT, 0)
    assert subject.camera_attempt_failed() == 0
    assert subject.camera_reconnected(1).accepted is False


def test_recovery_returns_to_idle_not_the_previous_mode() -> None:
    machine, subject = controller(S.POINTER_MODE)
    subject.fault(T.CAMERA_FAULT, 0)
    assert subject.reinitialize(1).accepted is True
    assert machine.state is S.IDLE

    assert machine.apply(T.LONG_PINCH, 2).accepted is False
    assert machine.state is S.IDLE


def test_recovery_triggers_are_rejected_outside_error() -> None:
    machine, subject = controller(S.ACTIVE)
    assert subject.reinitialize(0).accepted is False
    assert subject.camera_reconnected(1).accepted is False
    assert machine.state is S.ACTIVE


def test_deliberate_activation_is_still_required_after_recovery() -> None:
    machine, subject = controller(S.ACTIVE)
    subject.fault(T.UNRECOVERABLE_INTERNAL_FAULT, 0)
    assert subject.reinitialize(1).accepted is True
    assert machine.state is S.IDLE

    for trigger in (T.RESUME_CONFIRMED, T.PINCH_CONFIRMED, T.FIST_CONFIRMED):
        assert machine.apply(trigger, 2).accepted is False
    assert machine.apply(T.ACTIVATION_CONFIRMED, 3).accepted is True
    assert machine.state is S.ACTIVE


def test_a_cancelled_slide_command_cannot_be_replayed_after_recovery() -> None:
    machine, subject = controller(S.ACTIVE)
    manager = CommandManager()
    capabilities = capabilities_for(TargetKind.NORMAL_SLIDESHOW)
    assert manager.validate(Command.NEXT_SLIDE, machine.state, capabilities).allowed is True

    subject.fault(T.UNRECOVERABLE_ADAPTER_ERROR, 0)
    assert manager.validate(Command.NEXT_SLIDE, machine.state, capabilities).allowed is False

    subject.reinitialize(1)
    decision = manager.validate(Command.NEXT_SLIDE, machine.state, capabilities)
    assert decision.allowed is False
    assert decision.rejection is CommandRejection.STATE
