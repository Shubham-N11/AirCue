from __future__ import annotations

import logging
import threading
import time

import pytest

from aircue.dispatch.worker import (
    CommandWorker,
    DispatchStatus,
)
from aircue.presentation.adapter import (
    AdapterError,
    AdapterResult,
    Click,
    CommandPayload,
    DoubleClick,
    Navigate,
    PointerMove,
    Scroll,
    SlideDirection,
)
from aircue.presentation.target import TargetSnapshot

TARGET = TargetSnapshot(captured_ns=0)
NEXT = Navigate(SlideDirection.NEXT)
MS = 1_000_000


def ms(value: int) -> int:
    return value * MS


class Clock:
    def __init__(self) -> None:
        self.now = 0

    def __call__(self) -> int:
        return self.now


class RecordingAdapter:
    def __init__(self) -> None:
        self.executed: list[CommandPayload] = []
        self.refreshes = 0
        self.result = AdapterResult()
        self.gate: threading.Event | None = None
        self.started = threading.Event()

    def snapshot(self) -> TargetSnapshot:
        return TARGET

    def refresh(self) -> TargetSnapshot:
        self.refreshes += 1
        return TARGET

    def execute(self, payload: CommandPayload) -> AdapterResult:
        self.executed.append(payload)
        self.started.set()
        if self.gate is not None:
            self.gate.wait(5.0)
        return self.result


class RaisingAdapter(RecordingAdapter):
    def execute(self, payload: CommandPayload) -> AdapterResult:
        self.executed.append(payload)
        raise RuntimeError("sink exploded")


def build(
    adapter: RecordingAdapter | None = None,
    clock: Clock | None = None,
    **overrides,
) -> CommandWorker:
    values = {"clock_ns": clock or Clock(), "current_generation": lambda: 0}
    values.update(overrides)
    return CommandWorker(adapter or RecordingAdapter(), **values)


def wait_for(predicate, timeout_s: float = 2.0) -> bool:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.005)
    return predicate()


def submit(subject: CommandWorker, payload: CommandPayload, *, generation: int = 0) -> bool:
    return subject.submit(payload, generation=generation, target=TARGET, now_ns=0)


def test_one_worker_dispatches_in_fifo_order() -> None:
    adapter = RecordingAdapter()
    subject = build(adapter)
    payloads = [NEXT, Click(), Scroll(1)]
    assert all(submit(subject, payload) for payload in payloads)

    subject.start()
    assert wait_for(lambda: subject.stats().delivered == 3)
    assert adapter.executed == payloads
    assert subject.stop() is True


def test_only_one_worker_thread_is_created() -> None:
    subject = build()
    subject.start()
    first = subject._thread
    subject.start()
    assert subject._thread is first
    assert subject.stop() is True


def test_the_queue_is_bounded_at_eight() -> None:
    subject = build()
    assert all(submit(subject, Click()) for _ in range(8))
    assert subject.pending == 8

    assert submit(subject, Click()) is False
    assert subject.pending == 8
    assert subject.stats().rejected_full == 1
    assert subject.stop() is True


def test_adjacent_pointer_moves_coalesce_to_the_newest_position() -> None:
    adapter = RecordingAdapter()
    subject = build(adapter)
    assert submit(subject, PointerMove(1, 1)) is True
    assert submit(subject, PointerMove(2, 2)) is True
    assert subject.pending == 1
    assert subject.stats().coalesced == 1

    subject.start()
    assert wait_for(lambda: subject.stats().delivered == 1)
    assert adapter.executed == [PointerMove(2, 2)]
    outcomes = subject.drain_outcomes()
    assert [outcome.payload for outcome in outcomes] == [PointerMove(2, 2)]
    assert [outcome.sequence for outcome in outcomes] == [2]
    assert subject.stop() is True


def test_pointer_moves_do_not_coalesce_across_a_click() -> None:
    adapter = RecordingAdapter()
    subject = build(adapter)
    payloads = [PointerMove(1, 1), Click(), PointerMove(2, 2)]
    assert all(submit(subject, payload) for payload in payloads)
    assert subject.pending == 3
    assert subject.stats().coalesced == 0

    subject.start()
    assert wait_for(lambda: subject.stats().delivered == 3)
    assert adapter.executed == payloads
    assert subject.stop() is True


def test_a_pointer_move_coalesces_even_at_capacity() -> None:
    subject = build()
    assert all(submit(subject, Click()) for _ in range(7))
    assert submit(subject, PointerMove(1, 1)) is True
    assert subject.pending == 8

    assert submit(subject, PointerMove(2, 2)) is True
    assert subject.pending == 8
    assert subject.stats().coalesced == 1
    assert subject.stop() is True


@pytest.mark.parametrize(
    ("payload", "ttl_ms"),
    [
        (PointerMove(1, 1), 100),
        (Scroll(1), 150),
        (Click(), 250),
        (DoubleClick(), 250),
        (NEXT, 500),
    ],
)
def test_a_command_older_than_its_ttl_is_stale(
    payload: CommandPayload, ttl_ms: int
) -> None:
    clock = Clock()
    adapter = RecordingAdapter()
    subject = build(adapter, clock)
    assert submit(subject, payload) is True

    clock.now = ms(ttl_ms + 1)
    subject.start()
    assert wait_for(lambda: subject.stats().stale == 1)

    outcome = subject.drain_outcomes()[0]
    assert outcome.status is DispatchStatus.STALE_COMMAND
    assert outcome.error is AdapterError.STALE_COMMAND
    assert adapter.executed == []
    assert subject.stop() is True


def test_a_command_at_exactly_its_ttl_is_dispatched() -> None:
    clock = Clock()
    adapter = RecordingAdapter()
    subject = build(adapter, clock)
    assert submit(subject, PointerMove(1, 1)) is True

    clock.now = ms(100)
    subject.start()
    assert wait_for(lambda: subject.stats().delivered == 1)
    assert adapter.executed == [PointerMove(1, 1)]
    assert subject.stop() is True


def test_an_older_state_generation_is_canceled_before_dispatch() -> None:
    generation = [1]
    adapter = RecordingAdapter()
    subject = build(adapter, current_generation=lambda: generation[0])
    assert submit(subject, NEXT, generation=1) is True

    generation[0] = 2
    subject.start()
    assert wait_for(lambda: subject.stats().canceled == 1)

    outcome = subject.drain_outcomes()[0]
    assert outcome.status is DispatchStatus.CANCELED
    assert outcome.error is None
    assert adapter.executed == []
    assert subject.stop() is True


def test_a_call_past_the_deadline_reports_timeout_without_retry() -> None:
    clock = Clock()
    adapter = RecordingAdapter()
    adapter.gate = threading.Event()
    subject = build(adapter, clock)
    assert submit(subject, NEXT) is True

    subject.start()
    assert adapter.started.wait(2.0)
    clock.now = ms(151)
    adapter.gate.set()

    assert wait_for(lambda: subject.stats().timeouts == 1)
    outcome = subject.drain_outcomes()[0]
    assert outcome.status is DispatchStatus.TIMEOUT
    assert outcome.error is AdapterError.TIMEOUT
    assert outcome.elapsed_ns == ms(151)
    assert adapter.executed == [NEXT]
    assert subject.stop() is True


def test_a_call_at_exactly_the_deadline_is_delivered() -> None:
    clock = Clock()
    adapter = RecordingAdapter()
    adapter.gate = threading.Event()
    subject = build(adapter, clock)
    assert submit(subject, NEXT) is True

    subject.start()
    assert adapter.started.wait(2.0)
    clock.now = ms(150)
    adapter.gate.set()

    assert wait_for(lambda: subject.stats().delivered == 1)
    assert subject.stats().timeouts == 0
    assert subject.stop() is True


def test_an_unresponsive_call_stops_dispatch_and_cancels_pending_work() -> None:
    clock = Clock()
    adapter = RecordingAdapter()
    adapter.gate = threading.Event()
    subject = build(adapter, clock)
    assert submit(subject, NEXT) is True
    assert submit(subject, Click()) is True

    subject.start()
    assert adapter.started.wait(2.0)

    clock.now = ms(300)
    assert subject.check_unresponsive() is False
    clock.now = ms(301)
    assert subject.check_unresponsive() is True
    adapter.gate.set()

    assert wait_for(lambda: subject.stats().canceled == 1)
    stats = subject.stats()
    assert stats.timeouts == 1
    assert stats.canceled == 1
    assert stats.unresponsive is True
    assert adapter.executed == [NEXT]
    assert submit(subject, Scroll(1)) is False
    assert subject.stop() is True


def test_an_adapter_error_is_reported_without_retry() -> None:
    adapter = RecordingAdapter()
    adapter.result = AdapterResult(AdapterError.FOCUS_LOST, "foreground changed")
    subject = build(adapter)
    assert submit(subject, NEXT) is True

    subject.start()
    assert wait_for(lambda: subject.stats().errors == 1)

    outcome = subject.drain_outcomes()[0]
    assert outcome.status is DispatchStatus.REJECTED
    assert outcome.error is AdapterError.FOCUS_LOST
    assert outcome.detail == "foreground changed"
    assert adapter.executed == [NEXT]
    assert subject.stop() is True


def test_an_adapter_exception_is_reported_as_internal() -> None:
    adapter = RaisingAdapter()
    subject = build(adapter)
    assert submit(subject, NEXT) is True

    subject.start()
    assert wait_for(lambda: subject.stats().errors == 1)

    outcome = subject.drain_outcomes()[0]
    assert outcome.status is DispatchStatus.REJECTED
    assert outcome.error is AdapterError.INTERNAL
    assert "sink exploded" in outcome.detail
    assert subject.stop() is True


def test_shutdown_cancels_queued_work_without_dispatching() -> None:
    adapter = RecordingAdapter()
    subject = build(adapter)
    assert all(submit(subject, Click()) for _ in range(3))

    assert subject.stop() is True
    assert adapter.executed == []
    assert subject.pending == 0
    assert subject.stats().canceled == 3


def test_stop_joins_a_running_worker() -> None:
    adapter = RecordingAdapter()
    subject = build(adapter)
    subject.start()
    assert wait_for(lambda: adapter.refreshes >= 1)
    assert subject.stop() is True
    assert subject._thread is not None
    assert subject._thread.is_alive() is False


def test_a_wedged_call_is_abandoned_with_a_forced_shutdown_log(
    caplog: pytest.LogCaptureFixture,
) -> None:
    adapter = RecordingAdapter()
    adapter.gate = threading.Event()
    subject = build(adapter)
    assert submit(subject, NEXT) is True

    subject.start()
    assert adapter.started.wait(2.0)
    try:
        with caplog.at_level(logging.ERROR, logger="aircue.dispatch"):
            assert subject.stop(timeout_s=0.05) is False
        assert "forced abandonment" in caplog.text
        assert subject._thread is not None
        assert subject._thread.daemon is True
    finally:
        adapter.gate.set()
    assert wait_for(lambda: subject._thread is not None and not subject._thread.is_alive())


def test_the_worker_refreshes_the_target_while_idle() -> None:
    adapter = RecordingAdapter()
    subject = build(adapter)
    subject.start()
    assert wait_for(lambda: adapter.refreshes >= 1)
    assert subject.stop() is True
