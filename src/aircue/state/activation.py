"""Deliberate activation and resume, gated on an identified target."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from aircue.presentation.target import TargetKind, is_activatable
from aircue.state.states import InteractionState
from aircue.state.transitions import TransitionTrigger


class ActivationSource(StrEnum):
    GESTURE = "gesture"
    HOTKEY = "hotkey"


class ActivationRejection(StrEnum):
    NOT_IDLE_OR_PAUSED = "not_idle_or_paused"
    TARGET_NOT_READY = "target_not_ready"
    TARGET_NOT_ACTIVATABLE = "target_not_activatable"
    HOTKEY_CANNOT_RESUME = "hotkey_cannot_resume"


@dataclass(frozen=True)
class ActivationDecision:
    accepted: bool
    source: ActivationSource
    state: InteractionState
    trigger: TransitionTrigger | None = None
    rejection: ActivationRejection | None = None
    reason: str = ""


class ActivationController:
    """Decides whether a deliberate activation or resume may proceed.

    The recognizer already confirms the 800 ms activation hold and the 250 ms
    resume hold; this gate receives only an attempted activation and checks the
    target. Hand presence alone never produces an attempt.
    """

    def evaluate(
        self,
        state: InteractionState,
        kind: TargetKind,
        source: ActivationSource,
        *,
        target_ready: bool,
    ) -> ActivationDecision:
        if state not in (InteractionState.IDLE, InteractionState.PAUSED):
            return self._reject(
                state,
                source,
                ActivationRejection.NOT_IDLE_OR_PAUSED,
                f"activation is not available in {state.value}",
            )
        if not target_ready:
            return self._reject(
                state,
                source,
                ActivationRejection.TARGET_NOT_READY,
                "no foreground presentation target is available",
            )
        if not is_activatable(kind):
            return self._reject(
                state,
                source,
                ActivationRejection.TARGET_NOT_ACTIVATABLE,
                self._kind_reason(kind),
            )
        if state is InteractionState.PAUSED and source is not ActivationSource.GESTURE:
            return self._reject(
                state,
                source,
                ActivationRejection.HOTKEY_CANNOT_RESUME,
                "resume requires the thumbs-up hold",
            )
        trigger = (
            TransitionTrigger.ACTIVATION_CONFIRMED
            if state is InteractionState.IDLE
            else TransitionTrigger.RESUME_CONFIRMED
        )
        return ActivationDecision(accepted=True, source=source, state=state, trigger=trigger)

    @staticmethod
    def _kind_reason(kind: TargetKind) -> str:
        if kind is TargetKind.EDIT_MODE:
            return "a slideshow is required; PowerPoint is in edit mode"
        return f"target is {kind.value}, so activation is not allowed"

    @staticmethod
    def _reject(
        state: InteractionState,
        source: ActivationSource,
        rejection: ActivationRejection,
        reason: str,
    ) -> ActivationDecision:
        return ActivationDecision(
            accepted=False,
            source=source,
            state=state,
            rejection=rejection,
            reason=reason,
        )
