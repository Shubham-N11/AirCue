"""Status feedback model and the port that renders it.

The port intentionally offers no focus or input operation: showing status must
never take foreground focus from the presentation.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Protocol

from aircue.presentation.target import TargetCapabilities, TargetKind, capabilities_for
from aircue.state.machine import TransitionRecord
from aircue.state.states import InteractionState

_PROMPTS: dict[InteractionState, str] = {
    InteractionState.IDLE: "Thumbs-up hold 0.8 s or Ctrl+Alt+A to activate",
    InteractionState.PAUSED: "Thumbs-up hold 0.25 s to resume",
}
_ATTENTION_STATES = (InteractionState.PAUSED, InteractionState.ERROR)


@dataclass(frozen=True)
class StatusModel:
    """Everything the status indicator shows at one moment."""

    state: InteractionState
    target_kind: TargetKind
    capabilities: TargetCapabilities
    prompt: str | None = None
    reason: str | None = None


class StatusIndicator(Protocol):
    def update(self, status: StatusModel) -> None:
        """Show the latest status without taking focus or intercepting input."""
        ...


class StatusFeedback:
    """Keeps the displayed status in step with transitions and target changes.

    The state thread owns this object, so no locking is needed.
    """

    def __init__(self, indicator: StatusIndicator) -> None:
        self._indicator = indicator
        self._status = StatusModel(
            state=InteractionState.INITIALIZING,
            target_kind=TargetKind.UNKNOWN,
            capabilities=capabilities_for(TargetKind.UNKNOWN),
        )

    @property
    def status(self) -> StatusModel:
        return self._status

    def transition(self, record: TransitionRecord) -> StatusModel:
        """Publish an accepted transition; a rejected record changes nothing."""
        if record.accepted:
            self._status = replace(
                self._status,
                state=record.resulting,
                prompt=_PROMPTS.get(record.resulting),
                reason=record.reason if record.resulting in _ATTENTION_STATES else None,
            )
            self._indicator.update(self._status)
        return self._status

    def target_changed(self, kind: TargetKind) -> StatusModel:
        self._status = replace(
            self._status,
            target_kind=kind,
            capabilities=capabilities_for(kind),
        )
        self._indicator.update(self._status)
        return self._status
