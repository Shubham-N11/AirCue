"""Context-sensitive mapping from confirmed gestures to semantic actions."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from aircue.gestures.temporal import TemporalValidator
from aircue.gestures.vocabulary import Gesture
from aircue.state.states import InteractionState


class GestureAction(StrEnum):
    ACTIVATE = "activate"
    RESUME_TRACKING = "resume_tracking"
    PAUSE_TRACKING = "pause_tracking"
    ENTER_SCROLL_MODE = "enter_scroll_mode"
    EXIT_SCROLL_MODE = "exit_scroll_mode"
    EXIT_REQUEST = "exit_request"
    ENTER_POINTER_MODE = "enter_pointer_mode"
    EXIT_POINTER_MODE = "exit_pointer_mode"
    CLICK_CANDIDATE = "click_candidate"
    DOUBLE_CLICK = "double_click"
    NEXT_SLIDE = "next_slide"
    PREV_SLIDE = "prev_slide"
    SCROLL = "scroll"
    POINTER_MOVEMENT = "pointer_movement"


@dataclass(frozen=True)
class SemanticEvent:
    action: GestureAction
    gesture: Gesture
    onset_ns: int
    onset_sequence: int
    timestamp_ns: int
    confidence: float


_ACTIONS: dict[tuple[InteractionState, Gesture], GestureAction] = {
    (InteractionState.IDLE, Gesture.THUMBS_UP): GestureAction.ACTIVATE,
    (InteractionState.PAUSED, Gesture.THUMBS_UP): GestureAction.RESUME_TRACKING,
    (InteractionState.ACTIVE, Gesture.FIST): GestureAction.PAUSE_TRACKING,
    (InteractionState.POINTER_MODE, Gesture.FIST): GestureAction.PAUSE_TRACKING,
    (InteractionState.SCROLL_MODE, Gesture.FIST): GestureAction.PAUSE_TRACKING,
    (InteractionState.ACTIVE, Gesture.PEACE): GestureAction.ENTER_SCROLL_MODE,
    (InteractionState.SCROLL_MODE, Gesture.PEACE): GestureAction.EXIT_SCROLL_MODE,
    (InteractionState.IDLE, Gesture.SHAKA): GestureAction.EXIT_REQUEST,
    (InteractionState.ACTIVE, Gesture.SHAKA): GestureAction.EXIT_REQUEST,
    (InteractionState.PAUSED, Gesture.SHAKA): GestureAction.EXIT_REQUEST,
    (InteractionState.POINTER_MODE, Gesture.SHAKA): GestureAction.EXIT_REQUEST,
    (InteractionState.SCROLL_MODE, Gesture.SHAKA): GestureAction.EXIT_REQUEST,
    (InteractionState.ERROR, Gesture.SHAKA): GestureAction.EXIT_REQUEST,
}


class SemanticMapper:
    """Confirms static gestures with state-specific hold windows.

    Only gestures mapped in the current state can confirm. A state change clears
    pending confirmations so a hold never carries across a transition.
    """

    def __init__(
        self,
        *,
        activation_hold_ms: int = 800,
        resume_hold_ms: int = 250,
        fist_confirm_ms: int = 200,
        peace_confirm_ms: int = 250,
        shaka_hold_ms: int = 1500,
        gesture_cooldown_ms: int = 500,
        rearm_ms: int = 300,
        confidence_threshold: float = 0.5,
    ) -> None:
        shaka = {Gesture.SHAKA: shaka_hold_ms}
        windows: dict[InteractionState, dict[Gesture, int]] = {
            InteractionState.IDLE: {
                Gesture.THUMBS_UP: activation_hold_ms,
                **shaka,
            },
            InteractionState.PAUSED: {
                Gesture.THUMBS_UP: resume_hold_ms,
                **shaka,
            },
            InteractionState.ACTIVE: {
                Gesture.FIST: fist_confirm_ms,
                Gesture.PEACE: peace_confirm_ms,
                **shaka,
            },
            InteractionState.POINTER_MODE: {
                Gesture.FIST: fist_confirm_ms,
                **shaka,
            },
            InteractionState.SCROLL_MODE: {
                Gesture.FIST: fist_confirm_ms,
                Gesture.PEACE: peace_confirm_ms,
                **shaka,
            },
            InteractionState.ERROR: shaka,
        }
        self._validators = {
            state: TemporalValidator(
                state_windows,
                cooldown_ms=gesture_cooldown_ms,
                rearm_ms=rearm_ms,
                confidence_threshold=confidence_threshold,
            )
            for state, state_windows in windows.items()
        }
        self._state: InteractionState | None = None

    def reset(self) -> None:
        for validator in self._validators.values():
            validator.reset()
        self._state = None

    def update(
        self,
        gesture: Gesture | None,
        confidence: float,
        state: InteractionState,
        timestamp_ns: int,
        *,
        sequence: int = 0,
    ) -> SemanticEvent | None:
        if state is not self._state:
            self.reset()
            self._state = state
        validator = self._validators.get(state)
        if validator is None:
            return None
        # Gestures without a mapping count as neutral so they cancel a pending hold.
        candidate = gesture if (state, gesture) in _ACTIONS else None
        confirmed = validator.update(candidate, confidence, timestamp_ns, sequence=sequence)
        if confirmed is None:
            return None
        return SemanticEvent(
            action=_ACTIONS[(state, confirmed.gesture)],
            gesture=confirmed.gesture,
            onset_ns=confirmed.onset_ns,
            onset_sequence=confirmed.onset_sequence,
            timestamp_ns=confirmed.timestamp_ns,
            confidence=confirmed.confidence,
        )
