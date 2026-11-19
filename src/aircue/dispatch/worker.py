"""Bounded FIFO command worker from design.md D12.

One daemon thread executes envelopes in order, enforces per-command TTLs and
state-generation cancellation, reports a structured outcome for every envelope,
and stops dispatching when the adapter stops acknowledging.
"""

from __future__ import annotations

import logging
import threading
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, replace
from enum import StrEnum

from aircue.diagnostics.session_log import record_event
from aircue.performance.timing import FrameTimings, Stage
from aircue.presentation.adapter import (
    AdapterError,
    AdapterResult,
    Click,
    CommandPayload,
    DoubleClick,
    Navigate,
    PointerMove,
    PresentationAdapter,
    Scroll,
)
from aircue.presentation.target import TargetSnapshot

logger = logging.getLogger("aircue.dispatch")


class DispatchStatus(StrEnum):
    DELIVERED = "delivered"
    REJECTED = "rejected"
    STALE_COMMAND = "stale_command"
    CANCELED = "canceled"
    TIMEOUT = "timeout"


@dataclass(frozen=True)
class CommandEnvelope:
    sequence: int
    generation: int
    target: TargetSnapshot
    payload: CommandPayload
    enqueued_ns: int
    expires_ns: int
    timings: FrameTimings | None = None
    enqueued_perf_ns: int | None = None


@dataclass(frozen=True)
class DispatchOutcome:
    sequence: int
    payload: CommandPayload
    status: DispatchStatus
    error: AdapterError | None = None
    detail: str = ""
    elapsed_ns: int = 0
    timings: FrameTimings | None = None


@dataclass(frozen=True)
class DispatchStats:
    submitted: int = 0
    coalesced: int = 0
    rejected_full: int = 0
    stale: int = 0
    canceled: int = 0
    delivered: int = 0
    errors: int = 0
    timeouts: int = 0
    pending: int = 0
    unresponsive: bool = False


class CommandWorker:
    """Runs one adapter call at a time and never retries a command."""

    def __init__(
        self,
        adapter: PresentationAdapter,
        current_generation: Callable[[], int],
        *,
        queue_size: int = 8,
        pointer_ttl_ms: int = 100,
        scroll_ttl_ms: int = 150,
        click_ttl_ms: int = 250,
        navigation_ttl_ms: int = 500,
        deadline_ms: int = 150,
        unresponsive_ms: int = 300,
        refresh_ms: int = 250,
        clock_ns: Callable[[], int] = time.monotonic_ns,
    ) -> None:
        self._adapter = adapter
        self._current_generation = current_generation
        self._queue_size = queue_size
        self._ttl_ns = {
            "pointer": pointer_ttl_ms * 1_000_000,
            "scroll": scroll_ttl_ms * 1_000_000,
            "click": click_ttl_ms * 1_000_000,
            "navigation": navigation_ttl_ms * 1_000_000,
        }
        self._deadline_ns = deadline_ms * 1_000_000
        self._unresponsive_ns = unresponsive_ms * 1_000_000
        self._refresh_ns = refresh_ms * 1_000_000
        self._clock_ns = clock_ns

        self._condition = threading.Condition()
        self._queue: deque[CommandEnvelope] = deque()
        self._outcomes: deque[DispatchOutcome] = deque(maxlen=64)
        self._sequence = 0
        self._stats = DispatchStats()
        self._thread: threading.Thread | None = None
        self._stopping = False
        self._unresponsive = False
        self._in_call = False
        self._call_started_ns: int | None = None
        self._last_refresh_ns: int | None = None

    @property
    def pending(self) -> int:
        with self._condition:
            return len(self._queue)

    def stats(self) -> DispatchStats:
        with self._condition:
            return replace(
                self._stats,
                pending=len(self._queue),
                unresponsive=self._unresponsive,
            )

    def drain_outcomes(self) -> tuple[DispatchOutcome, ...]:
        with self._condition:
            outcomes = tuple(self._outcomes)
            self._outcomes.clear()
        return outcomes

    def start(self) -> None:
        with self._condition:
            if self._thread is not None or self._stopping:
                return
            self._thread = threading.Thread(
                target=self._run, name="aircue-command-worker", daemon=True
            )
            self._thread.start()

    def stop(self, *, timeout_s: float = 1.0) -> bool:
        """Stop acceptance, cancel queued work, and join once."""
        with self._condition:
            self._stopping = True
            self._condition.notify_all()
        self._cancel_queued("worker stopping")
        thread = self._thread
        if thread is None:
            return True
        thread.join(timeout_s)
        if thread.is_alive():
            logger.error(
                "command worker did not stop within %.2f s; "
                "forced abandonment of the daemon thread",
                timeout_s,
            )
            record_event(
                "fault",
                generation=self._current_generation(),
                level=logging.ERROR,
                reason="command worker did not stop",
                timeout_s=timeout_s,
            )
            return False
        return True

    def submit(
        self,
        payload: CommandPayload,
        *,
        generation: int,
        target: TargetSnapshot,
        now_ns: int | None = None,
        timings: FrameTimings | None = None,
    ) -> bool:
        """Queue one command; False when stopped, unresponsive, or full."""
        now = self._clock_ns() if now_ns is None else now_ns
        with self._condition:
            if self._stopping or self._unresponsive:
                return False
            envelope = self._envelope(
                payload,
                generation,
                target,
                now,
                timings=timings,
                enqueued_perf_ns=(
                    time.perf_counter_ns() if timings is not None else None
                ),
            )
            tail = self._queue[-1] if self._queue else None
            coalesced = (
                tail is not None
                and isinstance(tail.payload, PointerMove)
                and isinstance(payload, PointerMove)
            )
            if coalesced:
                self._queue[-1] = envelope
                self._stats = replace(
                    self._stats,
                    submitted=self._stats.submitted + 1,
                    coalesced=self._stats.coalesced + 1,
                )
            elif len(self._queue) >= self._queue_size:
                self._stats = replace(
                    self._stats, rejected_full=self._stats.rejected_full + 1
                )
                return False
            else:
                self._queue.append(envelope)
                self._stats = replace(self._stats, submitted=self._stats.submitted + 1)
                self._condition.notify()
        record_event(
            "dispatch",
            generation=envelope.generation,
            sequence=envelope.sequence,
            command=type(payload).__name__,
            coalesced=coalesced,
            timestamp_ns=envelope.enqueued_ns,
            expires_ns=envelope.expires_ns,
        )
        return True

    def check_unresponsive(self, now_ns: int | None = None) -> bool:
        """True once a call has gone unacknowledged past the threshold.

        The state thread polls this while a Win32 call is blocked; the worker
        cannot interrupt the call itself, but it stops dispatching afterwards.
        """
        with self._condition:
            if self._unresponsive:
                return True
            if not self._in_call or self._call_started_ns is None:
                return False
            now = self._clock_ns() if now_ns is None else now_ns
            if now - self._call_started_ns > self._unresponsive_ns:
                self._unresponsive = True
                logger.error(
                    "adapter call exceeded %d ms without acknowledgement; dispatch will stop",
                    self._unresponsive_ns // 1_000_000,
                )
                record_event(
                    "fault",
                    generation=self._current_generation(),
                    level=logging.ERROR,
                    reason="adapter unresponsive",
                    threshold_ms=self._unresponsive_ns // 1_000_000,
                    timestamp_ns=now,
                )
                return True
            return False

    def _envelope(
        self,
        payload: CommandPayload,
        generation: int,
        target: TargetSnapshot,
        now_ns: int,
        *,
        timings: FrameTimings | None = None,
        enqueued_perf_ns: int | None = None,
    ) -> CommandEnvelope:
        self._sequence += 1
        return CommandEnvelope(
            sequence=self._sequence,
            generation=generation,
            target=target,
            payload=payload,
            enqueued_ns=now_ns,
            expires_ns=now_ns + self._ttl_for(payload),
            timings=timings,
            enqueued_perf_ns=enqueued_perf_ns,
        )

    def _ttl_for(self, payload: CommandPayload) -> int:
        if isinstance(payload, PointerMove):
            return self._ttl_ns["pointer"]
        if isinstance(payload, Scroll):
            return self._ttl_ns["scroll"]
        if isinstance(payload, (Click, DoubleClick)):
            return self._ttl_ns["click"]
        if isinstance(payload, Navigate):
            return self._ttl_ns["navigation"]
        return 0

    def _run(self) -> None:
        while True:
            envelope = self._next()
            if envelope is None:
                return
            self._dispatch(envelope)
            if self._unresponsive:
                self._cancel_queued("adapter marked unresponsive")
                return

    def _next(self) -> CommandEnvelope | None:
        while True:
            with self._condition:
                while not self._queue and not self._stopping:
                    remaining = self._refresh_in()
                    if remaining <= 0:
                        break
                    self._condition.wait(remaining / 1_000_000_000)
                if self._stopping:
                    return None
                if self._queue:
                    return self._queue.popleft()
            self._refresh()

    def _refresh_in(self) -> int:
        if self._last_refresh_ns is None:
            return 0
        return self._last_refresh_ns + self._refresh_ns - self._clock_ns()

    def _refresh(self) -> None:
        try:
            self._adapter.refresh()
        except Exception as error:
            logger.warning("target refresh failed: %s", error)
        self._last_refresh_ns = self._clock_ns()

    def _dispatch(self, envelope: CommandEnvelope) -> None:
        if envelope.timings is not None and envelope.enqueued_perf_ns is not None:
            envelope.timings.record(
                Stage.DISPATCH_QUEUE_WAIT,
                envelope.enqueued_perf_ns,
                time.perf_counter_ns(),
            )
        with self._condition:
            stopped = self._stopping or self._unresponsive
        if stopped:
            self._record(envelope, DispatchStatus.CANCELED, detail="worker stopped")
            return
        now = self._clock_ns()
        if now > envelope.expires_ns:
            self._record(
                envelope,
                DispatchStatus.STALE_COMMAND,
                error=AdapterError.STALE_COMMAND,
                detail="command TTL expired",
            )
            return
        if envelope.generation < self._current_generation():
            self._record(
                envelope,
                DispatchStatus.CANCELED,
                detail="state generation changed before dispatch",
            )
            return

        started_ns = self._clock_ns()
        with self._condition:
            self._in_call = True
            self._call_started_ns = started_ns
        execution_started_ns = time.perf_counter_ns()
        try:
            result = self._adapter.execute(envelope.payload)
        except Exception as error:
            result = AdapterResult(AdapterError.INTERNAL, str(error))
        finally:
            if envelope.timings is not None:
                envelope.timings.record(
                    Stage.ADAPTER_EXECUTION,
                    execution_started_ns,
                    time.perf_counter_ns(),
                )
            elapsed_ns = self._clock_ns() - started_ns
            with self._condition:
                self._in_call = False
                self._call_started_ns = None
            self._last_refresh_ns = self._clock_ns()

        if elapsed_ns > self._unresponsive_ns:
            with self._condition:
                self._unresponsive = True
            self._record(
                envelope,
                DispatchStatus.TIMEOUT,
                error=AdapterError.TIMEOUT,
                detail=(
                    f"adapter unresponsive after {elapsed_ns / 1_000_000:.1f} ms; "
                    "no acknowledgement"
                ),
                elapsed_ns=elapsed_ns,
            )
            return
        if elapsed_ns > self._deadline_ns:
            self._record(
                envelope,
                DispatchStatus.TIMEOUT,
                error=AdapterError.TIMEOUT,
                detail=f"adapter call exceeded the {self._deadline_ns // 1_000_000} ms deadline",
                elapsed_ns=elapsed_ns,
            )
            return
        if result.error is not None:
            self._record(
                envelope,
                DispatchStatus.REJECTED,
                error=result.error,
                detail=result.detail,
                elapsed_ns=elapsed_ns,
            )
            return
        self._record(envelope, DispatchStatus.DELIVERED, elapsed_ns=elapsed_ns)

    def _cancel_queued(self, reason: str) -> None:
        with self._condition:
            queued = tuple(self._queue)
            self._queue.clear()
            self._condition.notify_all()
        for envelope in queued:
            self._record(envelope, DispatchStatus.CANCELED, detail=reason)

    def _record(
        self,
        envelope: CommandEnvelope,
        status: DispatchStatus,
        *,
        error: AdapterError | None = None,
        detail: str = "",
        elapsed_ns: int = 0,
    ) -> None:
        outcome = DispatchOutcome(
            sequence=envelope.sequence,
            payload=envelope.payload,
            status=status,
            error=error,
            detail=detail,
            elapsed_ns=elapsed_ns,
            timings=envelope.timings,
        )
        with self._condition:
            self._outcomes.append(outcome)
            stats = self._stats
            if status is DispatchStatus.DELIVERED:
                stats = replace(stats, delivered=stats.delivered + 1)
            elif status is DispatchStatus.REJECTED:
                stats = replace(stats, errors=stats.errors + 1)
            elif status is DispatchStatus.STALE_COMMAND:
                stats = replace(stats, stale=stats.stale + 1)
            elif status is DispatchStatus.CANCELED:
                stats = replace(stats, canceled=stats.canceled + 1)
            elif status is DispatchStatus.TIMEOUT:
                stats = replace(stats, timeouts=stats.timeouts + 1)
            self._stats = stats
        record_event(
            "adapter",
            generation=envelope.generation,
            sequence=envelope.sequence,
            command=type(envelope.payload).__name__,
            status=status.value,
            error=None if error is None else error.value,
            detail=detail,
            elapsed_ns=elapsed_ns,
            timestamp_ns=self._clock_ns(),
        )
