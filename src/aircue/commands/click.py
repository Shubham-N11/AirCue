"""Double-click arbitration from design.md D9."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from aircue.gestures.semantic import GestureAction, SemanticEvent
from aircue.gestures.vocabulary import Gesture
from aircue.state.machine import StateMachine, TransitionRecord
from aircue.state.states import InteractionState
from aircue.state.transitions import TransitionTrigger


class ClickDispatch(StrEnum):
    SINGLE = "single"
    DOUBLE = "double"


class ClickArbiter:
    """Holds one click candidate for the double-click window.

    A second candidate inside the half-open window dispatches one double-click
    immediately. A candidate at the deadline is outside the window: the first
    single click dispatches and the new candidate starts a fresh window.
    """

    def __init__(self, *, double_click_window_ms: int = 350) -> None:
        if double_click_window_ms <= 0:
            raise ValueError("double_click_window_ms must be positive")
        self._window_ns = double_click_window_ms * 1_000_000
        self._deadline_ns: int | None = None

    @property
    def pending(self) -> bool:
        return self._deadline_ns is not None

    def candidate(self, now_ns: int) -> ClickDispatch | None:
        """Record one valid release and return a dispatch if it resolves one."""
        expired = self.advance(now_ns)
        if self._deadline_ns is not None:
            self._deadline_ns = None
            return ClickDispatch.DOUBLE
        self._deadline_ns = now_ns + self._window_ns
        return expired

    def advance(self, now_ns: int) -> ClickDispatch | None:
        """Dispatch the pending single click once the window has expired."""
        if self._deadline_ns is None or now_ns < self._deadline_ns:
            return None
        self._deadline_ns = None
        return ClickDispatch.SINGLE

    def cancel(self) -> None:
        """Drop a pending click without dispatching it."""
        self._deadline_ns = None


@dataclass(frozen=True)
class ClickUpdate:
    dispatch: ClickDispatch | None = None
    transition: TransitionRecord | None = None


class ClickController:
    """Applies click-related gesture events to the arbiter and state machine.

    Long pinch owns the click policy: it cancels a pending click and applies the
    LONG_PINCH row, which exits POINTER_MODE to ACTIVE. Its release produces no
    candidate, so nothing is dispatched after the exit.
    """

    def __init__(
        self, machine: StateMachine, *, double_click_window_ms: int = 350
    ) -> None:
        self._machine = machine
        self._arbiter = ClickArbiter(double_click_window_ms=double_click_window_ms)

    @property
    def pending(self) -> bool:
        return self._arbiter.pending

    def on_event(self, event: SemanticEvent) -> ClickUpdate:
        if event.action is GestureAction.CLICK_CANDIDATE:
            if self._machine.state is not InteractionState.POINTER_MODE:
                return ClickUpdate()
            return ClickUpdate(dispatch=self._arbiter.candidate(event.timestamp_ns))
        if (
            event.action is GestureAction.EXIT_POINTER_MODE
            and event.gesture is Gesture.PINCH
        ):
            self._arbiter.cancel()
            return ClickUpdate(
                transition=self._machine.apply(
                    TransitionTrigger.LONG_PINCH,
                    event.timestamp_ns,
                    reason="long pinch",
                )
            )
        return ClickUpdate()

    def advance(self, now_ns: int) -> ClickDispatch | None:
        return self._arbiter.advance(now_ns)

    def cancel(self) -> None:
        self._arbiter.cancel()
