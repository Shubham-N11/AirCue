"""Map adapter errors to the state-layer responses in design.md D12."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from aircue.presentation.adapter import AdapterError
from aircue.state.machine import StateMachine, TransitionRecord
from aircue.state.transitions import TransitionTrigger


class ErrorDisposition(StrEnum):
    PAUSE = "pause"
    DROP = "drop"
    ERROR = "error"


@dataclass(frozen=True)
class ErrorMapping:
    disposition: ErrorDisposition
    trigger: TransitionTrigger | None = None


# A recoverable target or focus failure pauses; a stale command is dropped and
# counted by the worker without a transition; every other adapter failure is
# unrecoverable and stops dispatch.
ERROR_MAPPINGS: dict[AdapterError, ErrorMapping] = {
    AdapterError.FOCUS_LOST: ErrorMapping(
        ErrorDisposition.PAUSE, TransitionTrigger.RECOVERABLE_ADAPTER_ERROR
    ),
    AdapterError.TARGET_CHANGED: ErrorMapping(
        ErrorDisposition.PAUSE, TransitionTrigger.RECOVERABLE_ADAPTER_ERROR
    ),
    AdapterError.TARGET_UNAVAILABLE: ErrorMapping(
        ErrorDisposition.PAUSE, TransitionTrigger.RECOVERABLE_ADAPTER_ERROR
    ),
    AdapterError.UNSUPPORTED_PRESENTER_VIEW: ErrorMapping(
        ErrorDisposition.PAUSE, TransitionTrigger.RECOVERABLE_ADAPTER_ERROR
    ),
    AdapterError.STALE_COMMAND: ErrorMapping(ErrorDisposition.DROP),
    AdapterError.INPUT_BLOCKED: ErrorMapping(
        ErrorDisposition.ERROR, TransitionTrigger.UNRECOVERABLE_ADAPTER_ERROR
    ),
    AdapterError.ADAPTER_UNAVAILABLE: ErrorMapping(
        ErrorDisposition.ERROR, TransitionTrigger.UNRECOVERABLE_ADAPTER_ERROR
    ),
    AdapterError.TIMEOUT: ErrorMapping(
        ErrorDisposition.ERROR, TransitionTrigger.UNRECOVERABLE_ADAPTER_ERROR
    ),
    AdapterError.INTERNAL: ErrorMapping(
        ErrorDisposition.ERROR, TransitionTrigger.UNRECOVERABLE_ADAPTER_ERROR
    ),
}


def apply_error(
    machine: StateMachine,
    error: AdapterError | None,
    timestamp_ns: int,
    *,
    detail: str = "",
) -> TransitionRecord | None:
    """Apply the mapped trigger, or drop the error without touching the machine.

    The machine still enforces the transition table, so a late recoverable
    outcome cannot change a state that has no row for it, and no error can
    recover the application or resume a previous mode.
    """
    if error is None:
        return None
    mapping = ERROR_MAPPINGS[error]
    if mapping.trigger is None:
        return None
    reason = f"{error.value}: {detail}" if detail else error.value
    return machine.apply(mapping.trigger, timestamp_ns, reason=reason)
