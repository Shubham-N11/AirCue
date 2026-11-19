"""Double-click arbitration from design.md D9."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from aircue.commands.commands import Command, CommandRejection
from aircue.commands.manager import CommandManager
from aircue.gestures.semantic import GestureAction, SemanticEvent
from aircue.gestures.vocabulary import Gesture
from aircue.performance.timing import FrameTimings
from aircue.presentation.adapter import Click, DoubleClick
from aircue.presentation.target import TargetCapabilities
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
class ClickOrigin:
    """The frame and onset that started the pending click window."""

    event: SemanticEvent
    timings: FrameTimings | None = None


@dataclass(frozen=True)
class ClickUpdate:
    dispatch: ClickDispatch | None = None
    transition: TransitionRecord | None = None
    origin: ClickOrigin | None = field(default=None, compare=False)


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
        self._pending_origin: ClickOrigin | None = None

    @property
    def pending(self) -> bool:
        return self._arbiter.pending

    def on_event(
        self, event: SemanticEvent, *, timings: FrameTimings | None = None
    ) -> ClickUpdate:
        if event.action is GestureAction.CLICK_CANDIDATE:
            if self._machine.state is not InteractionState.POINTER_MODE:
                return ClickUpdate()
            previous, self._pending_origin = self._pending_origin, None
            dispatch = self._arbiter.candidate(event.timestamp_ns)
            if dispatch is ClickDispatch.DOUBLE:
                return ClickUpdate(dispatch=dispatch, origin=previous)
            self._pending_origin = ClickOrigin(event, timings)
            return ClickUpdate(dispatch=dispatch, origin=previous)
        if (
            event.action is GestureAction.EXIT_POINTER_MODE
            and event.gesture is Gesture.PINCH
        ):
            self.cancel()
            return ClickUpdate(
                transition=self._machine.apply(
                    TransitionTrigger.LONG_PINCH,
                    event.timestamp_ns,
                    reason="long pinch",
                )
            )
        return ClickUpdate()

    def advance(self, now_ns: int) -> ClickUpdate:
        dispatch = self._arbiter.advance(now_ns)
        if dispatch is None:
            return ClickUpdate()
        origin, self._pending_origin = self._pending_origin, None
        return ClickUpdate(dispatch=dispatch, origin=origin)

    def cancel(self) -> None:
        self._arbiter.cancel()
        self._pending_origin = None


class ClickRejection(StrEnum):
    STATE = "state"
    CAPABILITY = "capability"
    FOCUS = "focus"


@dataclass(frozen=True)
class ClickDecision:
    """The command-path record for one arbitrated click; a rejection sends nothing."""

    command: Command
    state: InteractionState
    payload: Click | DoubleClick | None = None
    rejection: ClickRejection | None = None
    reason: str = ""

    @property
    def allowed(self) -> bool:
        return self.rejection is None


def gate_click(
    manager: CommandManager,
    dispatch: ClickDispatch,
    state: InteractionState,
    capabilities: TargetCapabilities,
    *,
    foreground: bool,
) -> ClickDecision:
    """Convert an arbitrated click into a payload, or record why it may not be sent."""
    if dispatch is ClickDispatch.SINGLE:
        command = Command.CLICK
        payload: Click | DoubleClick = Click()
    else:
        command = Command.DOUBLE_CLICK
        payload = DoubleClick()
    decision = manager.validate(command, state, capabilities)
    if decision.rejection is CommandRejection.STATE:
        return ClickDecision(
            command, state, rejection=ClickRejection.STATE, reason=decision.reason
        )
    if decision.rejection is CommandRejection.CAPABILITY:
        return ClickDecision(
            command, state, rejection=ClickRejection.CAPABILITY, reason=decision.reason
        )
    if not foreground:
        return ClickDecision(
            command,
            state,
            rejection=ClickRejection.FOCUS,
            reason=f"{command.value} requires a foreground presentation target",
        )
    return ClickDecision(command, state, payload=payload)
