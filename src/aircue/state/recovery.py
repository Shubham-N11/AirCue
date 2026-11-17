"""Cause-aware error recovery for the state layer.

Only design.md D3.1 recovery rows are used. The ERROR cause is remembered so a
camera reconnect cannot clear an adapter or internal error, and the reconnect
budget keeps a camera error from being retried forever.
"""

from __future__ import annotations

from aircue.state.machine import StateMachine, TransitionRecord
from aircue.state.states import InteractionState
from aircue.state.transitions import TransitionTrigger


class RecoveryController:
    """Applies faults and admits only the recovery paths D3.1 permits."""

    def __init__(
        self,
        machine: StateMachine,
        *,
        reconnect_attempts: int = 3,
        reconnect_backoff_ms: int = 500,
    ) -> None:
        self._machine = machine
        self._attempt_limit = reconnect_attempts
        self._attempts_left = 0
        self._backoff_ns = reconnect_backoff_ms * 1_000_000
        self._cause: TransitionTrigger | None = None

    @property
    def error_cause(self) -> TransitionTrigger | None:
        return self._cause

    @property
    def reconnect_attempts_left(self) -> int:
        return self._attempts_left

    @property
    def reconnect_backoff_ns(self) -> int:
        return self._backoff_ns

    def fault(
        self,
        trigger: TransitionTrigger,
        timestamp_ns: int,
        *,
        reason: str | None = None,
    ) -> TransitionRecord:
        """Apply an unrecoverable fault; a camera fault arms the reconnect budget."""
        record = self._machine.apply(trigger, timestamp_ns, reason=reason)
        if record.accepted and record.resulting is InteractionState.ERROR:
            self._cause = trigger
            self._attempts_left = (
                self._attempt_limit if trigger is TransitionTrigger.CAMERA_FAULT else 0
            )
        return record

    def camera_attempt_failed(self) -> int:
        """Count one failed reconnect attempt and report how many remain."""
        if self._attempts_left > 0:
            self._attempts_left -= 1
        return self._attempts_left

    def reinitialize(self, timestamp_ns: int, *, reason: str | None = None) -> TransitionRecord:
        """Explicit reinitialization, permitted after any error."""
        record = self._machine.apply(
            TransitionTrigger.REINITIALIZATION_SUCCEEDED, timestamp_ns, reason=reason
        )
        self._clear_after_recovery(record)
        return record

    def camera_reconnected(
        self, timestamp_ns: int, *, reason: str | None = None
    ) -> TransitionRecord:
        """Bounded camera reconnect, permitted only after a camera fault."""
        if self._machine.state is InteractionState.ERROR:
            if self._cause is not TransitionTrigger.CAMERA_FAULT:
                cause = self._cause.value if self._cause else "unrecorded"
                return self._reject(f"camera reconnect cannot clear a {cause} error", timestamp_ns)
            if self._attempts_left == 0:
                return self._reject(
                    "camera reconnect attempts are exhausted; reinitialize explicitly",
                    timestamp_ns,
                )
        record = self._machine.apply(
            TransitionTrigger.CAMERA_RECONNECT_SUCCEEDED, timestamp_ns, reason=reason
        )
        self._clear_after_recovery(record)
        return record

    def _clear_after_recovery(self, record: TransitionRecord) -> None:
        if record.accepted and record.resulting is InteractionState.IDLE:
            self._cause = None
            self._attempts_left = 0

    def _reject(self, reason: str, timestamp_ns: int) -> TransitionRecord:
        state = self._machine.state
        return TransitionRecord(
            accepted=False,
            previous=state,
            trigger=TransitionTrigger.CAMERA_RECONNECT_SUCCEEDED,
            resulting=state,
            reason=reason,
            generation=self._machine.generation,
            timestamp_ns=timestamp_ns,
        )
