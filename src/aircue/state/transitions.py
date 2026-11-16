"""The authoritative interaction-state transition table from design.md D3.1.

This table is the single source of truth. No other transition is permitted.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from aircue.state.states import InteractionState


class Termination(StrEnum):
    """Target of the one transition that ends the runtime."""

    TERMINATED = "terminated"


class TransitionTrigger(StrEnum):
    INITIALIZATION_SUCCEEDED = "initialization_succeeded"
    INITIALIZATION_FAILED = "initialization_failed"
    EXIT_REQUEST = "exit_request"
    ACTIVATION_CONFIRMED = "activation_confirmed"
    TRACKING_LOSS = "tracking_loss"
    TRACKING_TIMEOUT = "tracking_timeout"
    FOCUS_LOSS = "focus_loss"
    DEACTIVATION_HOTKEY = "deactivation_hotkey"
    UNRECOVERABLE_FAULT = "unrecoverable_fault"
    FIST_CONFIRMED = "fist_confirmed"
    PINCH_CONFIRMED = "pinch_confirmed"
    PEACE_CONFIRMED = "peace_confirmed"
    RECOVERABLE_ADAPTER_ERROR = "recoverable_adapter_error"
    UNRECOVERABLE_ADAPTER_ERROR = "unrecoverable_adapter_error"
    CAMERA_FAULT = "camera_fault"
    UNRECOVERABLE_INTERNAL_FAULT = "unrecoverable_internal_fault"
    RESUME_CONFIRMED = "resume_confirmed"
    LONG_PINCH = "long_pinch"
    REINITIALIZATION_SUCCEEDED = "reinitialization_succeeded"
    CAMERA_RECONNECT_SUCCEEDED = "camera_reconnect_succeeded"
    CLEANUP_COMPLETED = "cleanup_completed"


@dataclass(frozen=True)
class Transition:
    source: InteractionState
    trigger: TransitionTrigger
    target: InteractionState | Termination

    @property
    def changes_state(self) -> bool:
        """False for the listed triggers that are recognised no-ops."""
        return self.target is not self.source


TRANSITIONS: tuple[Transition, ...] = (
    Transition(
        InteractionState.INITIALIZING,
        TransitionTrigger.INITIALIZATION_SUCCEEDED,
        InteractionState.IDLE,
    ),
    Transition(
        InteractionState.INITIALIZING,
        TransitionTrigger.INITIALIZATION_FAILED,
        InteractionState.ERROR,
    ),
    Transition(
        InteractionState.INITIALIZING, TransitionTrigger.EXIT_REQUEST, InteractionState.EXITING
    ),
    Transition(
        InteractionState.IDLE, TransitionTrigger.ACTIVATION_CONFIRMED, InteractionState.ACTIVE
    ),
    Transition(InteractionState.IDLE, TransitionTrigger.TRACKING_LOSS, InteractionState.IDLE),
    Transition(InteractionState.IDLE, TransitionTrigger.FOCUS_LOSS, InteractionState.IDLE),
    Transition(InteractionState.IDLE, TransitionTrigger.DEACTIVATION_HOTKEY, InteractionState.IDLE),
    Transition(InteractionState.IDLE, TransitionTrigger.EXIT_REQUEST, InteractionState.EXITING),
    Transition(
        InteractionState.IDLE, TransitionTrigger.UNRECOVERABLE_FAULT, InteractionState.ERROR
    ),
    Transition(InteractionState.ACTIVE, TransitionTrigger.FIST_CONFIRMED, InteractionState.PAUSED),
    Transition(
        InteractionState.ACTIVE, TransitionTrigger.PINCH_CONFIRMED, InteractionState.POINTER_MODE
    ),
    Transition(
        InteractionState.ACTIVE, TransitionTrigger.PEACE_CONFIRMED, InteractionState.SCROLL_MODE
    ),
    Transition(InteractionState.ACTIVE, TransitionTrigger.TRACKING_TIMEOUT, InteractionState.IDLE),
    Transition(InteractionState.ACTIVE, TransitionTrigger.FOCUS_LOSS, InteractionState.PAUSED),
    Transition(
        InteractionState.ACTIVE,
        TransitionTrigger.RECOVERABLE_ADAPTER_ERROR,
        InteractionState.PAUSED,
    ),
    Transition(
        InteractionState.ACTIVE,
        TransitionTrigger.UNRECOVERABLE_ADAPTER_ERROR,
        InteractionState.ERROR,
    ),
    Transition(InteractionState.ACTIVE, TransitionTrigger.CAMERA_FAULT, InteractionState.ERROR),
    Transition(
        InteractionState.ACTIVE,
        TransitionTrigger.UNRECOVERABLE_INTERNAL_FAULT,
        InteractionState.ERROR,
    ),
    Transition(
        InteractionState.ACTIVE, TransitionTrigger.DEACTIVATION_HOTKEY, InteractionState.IDLE
    ),
    Transition(InteractionState.ACTIVE, TransitionTrigger.EXIT_REQUEST, InteractionState.EXITING),
    Transition(
        InteractionState.PAUSED, TransitionTrigger.RESUME_CONFIRMED, InteractionState.ACTIVE
    ),
    Transition(InteractionState.PAUSED, TransitionTrigger.TRACKING_TIMEOUT, InteractionState.IDLE),
    Transition(
        InteractionState.PAUSED, TransitionTrigger.DEACTIVATION_HOTKEY, InteractionState.IDLE
    ),
    Transition(InteractionState.PAUSED, TransitionTrigger.EXIT_REQUEST, InteractionState.EXITING),
    Transition(
        InteractionState.PAUSED, TransitionTrigger.UNRECOVERABLE_FAULT, InteractionState.ERROR
    ),
    Transition(
        InteractionState.POINTER_MODE, TransitionTrigger.LONG_PINCH, InteractionState.ACTIVE
    ),
    Transition(
        InteractionState.POINTER_MODE, TransitionTrigger.FIST_CONFIRMED, InteractionState.PAUSED
    ),
    Transition(
        InteractionState.POINTER_MODE, TransitionTrigger.FOCUS_LOSS, InteractionState.PAUSED
    ),
    Transition(
        InteractionState.POINTER_MODE, TransitionTrigger.TRACKING_TIMEOUT, InteractionState.IDLE
    ),
    Transition(
        InteractionState.POINTER_MODE,
        TransitionTrigger.RECOVERABLE_ADAPTER_ERROR,
        InteractionState.PAUSED,
    ),
    Transition(
        InteractionState.POINTER_MODE,
        TransitionTrigger.UNRECOVERABLE_ADAPTER_ERROR,
        InteractionState.ERROR,
    ),
    Transition(
        InteractionState.POINTER_MODE, TransitionTrigger.CAMERA_FAULT, InteractionState.ERROR
    ),
    Transition(
        InteractionState.POINTER_MODE,
        TransitionTrigger.UNRECOVERABLE_INTERNAL_FAULT,
        InteractionState.ERROR,
    ),
    Transition(
        InteractionState.POINTER_MODE, TransitionTrigger.DEACTIVATION_HOTKEY, InteractionState.IDLE
    ),
    Transition(
        InteractionState.POINTER_MODE, TransitionTrigger.EXIT_REQUEST, InteractionState.EXITING
    ),
    Transition(
        InteractionState.SCROLL_MODE, TransitionTrigger.PEACE_CONFIRMED, InteractionState.ACTIVE
    ),
    Transition(
        InteractionState.SCROLL_MODE, TransitionTrigger.FIST_CONFIRMED, InteractionState.PAUSED
    ),
    Transition(InteractionState.SCROLL_MODE, TransitionTrigger.FOCUS_LOSS, InteractionState.PAUSED),
    Transition(
        InteractionState.SCROLL_MODE, TransitionTrigger.TRACKING_TIMEOUT, InteractionState.IDLE
    ),
    Transition(
        InteractionState.SCROLL_MODE,
        TransitionTrigger.RECOVERABLE_ADAPTER_ERROR,
        InteractionState.PAUSED,
    ),
    Transition(
        InteractionState.SCROLL_MODE,
        TransitionTrigger.UNRECOVERABLE_ADAPTER_ERROR,
        InteractionState.ERROR,
    ),
    Transition(
        InteractionState.SCROLL_MODE, TransitionTrigger.CAMERA_FAULT, InteractionState.ERROR
    ),
    Transition(
        InteractionState.SCROLL_MODE,
        TransitionTrigger.UNRECOVERABLE_INTERNAL_FAULT,
        InteractionState.ERROR,
    ),
    Transition(
        InteractionState.SCROLL_MODE, TransitionTrigger.DEACTIVATION_HOTKEY, InteractionState.IDLE
    ),
    Transition(
        InteractionState.SCROLL_MODE, TransitionTrigger.EXIT_REQUEST, InteractionState.EXITING
    ),
    Transition(
        InteractionState.ERROR, TransitionTrigger.REINITIALIZATION_SUCCEEDED, InteractionState.IDLE
    ),
    Transition(
        InteractionState.ERROR, TransitionTrigger.CAMERA_RECONNECT_SUCCEEDED, InteractionState.IDLE
    ),
    Transition(InteractionState.ERROR, TransitionTrigger.EXIT_REQUEST, InteractionState.EXITING),
    Transition(
        InteractionState.EXITING, TransitionTrigger.CLEANUP_COMPLETED, Termination.TERMINATED
    ),
)

_BY_KEY: dict[tuple[InteractionState, TransitionTrigger], Transition] = {
    (transition.source, transition.trigger): transition for transition in TRANSITIONS
}


def find_transition(source: InteractionState, trigger: TransitionTrigger) -> Transition | None:
    """Return the listed transition, or None when the pair is not permitted."""
    return _BY_KEY.get((source, trigger))
