from __future__ import annotations

import threading
import time

import pytest

from aircue.dispatch.errors import ERROR_MAPPINGS, ErrorDisposition, apply_error
from aircue.dispatch.worker import CommandWorker
from aircue.presentation.adapter import (
    AdapterError,
    AdapterResult,
    Click,
    CommandPayload,
    Navigate,
    SlideDirection,
)
from aircue.presentation.target import TargetSnapshot
from aircue.state.machine import StateMachine
from aircue.state.states import InteractionState
from aircue.state.transitions import TransitionTrigger

S = InteractionState
T = TransitionTrigger
TARGET = TargetSnapshot(captured_ns=0)
NEXT = Navigate(SlideDirection.NEXT)
ACTIVE_STATES = [S.ACTIVE, S.POINTER_MODE, S.SCROLL_MODE]
RECOVERABLE = [
    AdapterError.FOCUS_LOST,
    AdapterError.TARGET_CHANGED,
    AdapterError.TARGET_UNAVAILABLE,
    AdapterError.UNSUPPORTED_PRESENTER_VIEW,
]
UNRECOVERABLE = [
    AdapterError.INPUT_BLOCKED,
    AdapterError.ADAPTER_UNAVAILABLE,
    AdapterError.TIMEOUT,
    AdapterError.INTERNAL,
]


def test_every_adapter_error_has_a_mapping() -> None:
    assert set(ERROR_MAPPINGS) == set(AdapterError)


@pytest.mark.parametrize("state", ACTIVE_STATES)
@pytest.mark.parametrize("error", RECOVERABLE)
def test_recoverable_errors_pause_from_each_active_state(
    state: InteractionState, error: AdapterError
) -> None:
    machine = StateMachine(state)
    record = apply_error(machine, error, 0, detail="target lost")

    assert record is not None
    assert record.accepted is True
    assert machine.state is S.PAUSED
    assert record.trigger is T.RECOVERABLE_ADAPTER_ERROR
    assert record.generation == 1
    assert error.value in record.reason


@pytest.mark.parametrize("state", ACTIVE_STATES)
@pytest.mark.parametrize("error", UNRECOVERABLE)
def test_unrecoverable_errors_enter_error_from_each_active_state(
    state: InteractionState, error: AdapterError
) -> None:
    machine = StateMachine(state)
    record = apply_error(machine, error, 0)

    assert record is not None
    assert record.accepted is True
    assert machine.state is S.ERROR
    assert record.trigger is T.UNRECOVERABLE_ADAPTER_ERROR
    assert record.generation == 1


@pytest.mark.parametrize("state", [S.ACTIVE, S.PAUSED])
def test_a_stale_command_is_dropped_without_changing_state(
    state: InteractionState,
) -> None:
    machine = StateMachine(state)
    generation = machine.generation

    assert apply_error(machine, AdapterError.STALE_COMMAND, 0) is None
    assert machine.state is state
    assert machine.generation == generation


def test_stale_command_is_mapped_to_no_transition() -> None:
    mapping = ERROR_MAPPINGS[AdapterError.STALE_COMMAND]
    assert mapping.disposition is ErrorDisposition.DROP
    assert mapping.trigger is None


@pytest.mark.parametrize("error", RECOVERABLE)
def test_a_late_recoverable_error_does_not_change_paused(error: AdapterError) -> None:
    machine = StateMachine(S.PAUSED)
    generation = machine.generation

    record = apply_error(machine, error, 0)

    assert record is not None
    assert record.accepted is False
    assert machine.state is S.PAUSED
    assert machine.generation == generation
    assert record.reason


@pytest.mark.parametrize("error", list(AdapterError))
def test_idle_ignores_every_adapter_error(error: AdapterError) -> None:
    machine = StateMachine(S.IDLE)
    record = apply_error(machine, error, 0)
    assert record is None or record.accepted is False
    assert machine.state is S.IDLE


@pytest.mark.parametrize("error", list(AdapterError))
def test_error_never_recovers_and_never_resumes(error: AdapterError) -> None:
    machine = StateMachine(S.ERROR)
    record = apply_error(machine, error, 0)
    if record is not None:
        assert record.accepted is False
    assert machine.state is S.ERROR


def test_no_error_changes_nothing() -> None:
    machine = StateMachine(S.ACTIVE)
    assert apply_error(machine, None, 0) is None
    assert machine.state is S.ACTIVE
    assert machine.generation == 0


class BlockedAdapter:
    def __init__(self) -> None:
        self.executed: list[CommandPayload] = []

    def snapshot(self) -> TargetSnapshot:
        return TARGET

    def refresh(self) -> TargetSnapshot:
        return TARGET

    def execute(self, payload: CommandPayload) -> AdapterResult:
        self.executed.append(payload)
        return AdapterResult(AdapterError.INPUT_BLOCKED, "click was blocked")


def wait_for(predicate, timeout_s: float = 2.0) -> bool:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.005)
    return predicate()


def test_an_unrecoverable_outcome_is_applied_once_without_a_retry() -> None:
    machine = StateMachine(S.ACTIVE)
    adapter = BlockedAdapter()
    worker = CommandWorker(adapter, lambda: machine.generation)
    try:
        assert worker.submit(
            NEXT, generation=machine.generation, target=TARGET
        ) is True
        worker.start()
        assert wait_for(lambda: worker.stats().errors == 1)

        outcome = worker.drain_outcomes()[0]
        assert outcome.error is AdapterError.INPUT_BLOCKED
        record = apply_error(machine, outcome.error, 1, detail=outcome.detail)
        assert record is not None
        assert record.accepted is True
        assert machine.state is S.ERROR

        apply_error(machine, outcome.error, 2)
        assert machine.state is S.ERROR
        assert adapter.executed == [NEXT]
    finally:
        assert worker.stop() is True


def test_a_worker_timeout_maps_to_error_without_a_second_call() -> None:
    clock_time = [0]
    gate = threading.Event()
    started = threading.Event()

    class SlowAdapter(BlockedAdapter):
        def execute(self, payload: CommandPayload) -> AdapterResult:
            self.executed.append(payload)
            started.set()
            gate.wait(5.0)
            return AdapterResult()

    machine = StateMachine(S.POINTER_MODE)
    adapter = SlowAdapter()
    worker = CommandWorker(adapter, lambda: machine.generation, clock_ns=lambda: clock_time[0])
    try:
        assert worker.submit(NEXT, generation=machine.generation, target=TARGET) is True
        worker.start()
        assert started.wait(2.0)
        clock_time[0] = 151 * 1_000_000
        gate.set()
        assert wait_for(lambda: worker.stats().timeouts == 1)

        outcome = worker.drain_outcomes()[0]
        record = apply_error(machine, outcome.error, 1)
        assert record is not None
        assert machine.state is S.ERROR
        assert adapter.executed == [NEXT]
    finally:
        gate.set()
        assert worker.stop() is True


def test_click_is_not_retried_after_a_recoverable_failure() -> None:
    class FocusLostAdapter(BlockedAdapter):
        def execute(self, payload: CommandPayload) -> AdapterResult:
            self.executed.append(payload)
            return AdapterResult(AdapterError.FOCUS_LOST, "foreground changed")

    machine = StateMachine(S.POINTER_MODE)
    adapter = FocusLostAdapter()
    worker = CommandWorker(adapter, lambda: machine.generation)
    try:
        assert worker.submit(Click(), generation=machine.generation, target=TARGET) is True
        worker.start()
        assert wait_for(lambda: worker.stats().errors == 1)

        outcome = worker.drain_outcomes()[0]
        record = apply_error(machine, outcome.error, 1)
        assert record is not None
        assert machine.state is S.PAUSED
        assert adapter.executed == [Click()]
    finally:
        assert worker.stop() is True
