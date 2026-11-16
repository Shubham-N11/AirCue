"""Pinch hysteresis state machine with confirmation windows."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from aircue.gestures.semantic import GestureAction, SemanticEvent
from aircue.gestures.vocabulary import Gesture
from aircue.state.states import InteractionState
from aircue.vision.types import HandRecord


class PinchState(StrEnum):
    ARMED = "armed"
    CLOSING = "closing"
    PINCHED = "pinched"
    RELEASING = "releasing"
    AWAITING_REARM = "awaiting_rearm"


class PinchEventKind(StrEnum):
    INITIATED = "initiated"
    RELEASED = "released"


@dataclass(frozen=True)
class PinchEvent:
    kind: PinchEventKind
    onset_ns: int
    timestamp_ns: int
    distance: float
    held_ns: int | None = None


class PinchStateMachine:
    """Tracks one pinch cycle per neutral re-arm.

    Close, release, and re-arm each require their predicate to hold for the
    configured window. Frames without a valid pinch distance suspend the machine
    without changing the closed/armed state, so occlusion cannot produce a click.
    """

    def __init__(
        self,
        *,
        close_threshold: float = 0.22,
        release_threshold: float = 0.32,
        rearm_threshold: float = 0.40,
        close_confirm_ms: int = 100,
        release_confirm_ms: int = 100,
        rearm_confirm_ms: int = 300,
    ) -> None:
        self._close_threshold = close_threshold
        self._release_threshold = release_threshold
        self._rearm_threshold = rearm_threshold
        self._close_ns = close_confirm_ms * 1_000_000
        self._release_ns = release_confirm_ms * 1_000_000
        self._rearm_ns = rearm_confirm_ms * 1_000_000
        self._state = PinchState.ARMED
        self._pending_since_ns: int | None = None
        self._pinched_since_ns: int | None = None

    @property
    def state(self) -> PinchState:
        return self._state

    @property
    def is_closed(self) -> bool:
        return self._state is PinchState.PINCHED

    def reset(self) -> None:
        self._state = PinchState.ARMED
        self._pending_since_ns = None
        self._pinched_since_ns = None

    def pinched_ns(self, timestamp_ns: int) -> int | None:
        """Time since the pinch was confirmed, or None when not pinched."""
        if self._pinched_since_ns is None:
            return None
        return timestamp_ns - self._pinched_since_ns

    def update(self, hand: HandRecord | None, timestamp_ns: int) -> PinchEvent | None:
        distance = None if hand is None else hand.features.pinch_distance
        if distance is None:
            self._suspend()
            return None

        if self._state is PinchState.ARMED:
            return self._update_armed(distance, timestamp_ns)
        if self._state is PinchState.CLOSING:
            return self._update_closing(distance, timestamp_ns)
        if self._state is PinchState.PINCHED:
            return self._update_pinched(distance, timestamp_ns)
        if self._state is PinchState.RELEASING:
            return self._update_releasing(distance, timestamp_ns)
        return self._update_awaiting_rearm(distance, timestamp_ns)

    def _update_armed(self, distance: float, timestamp_ns: int) -> PinchEvent | None:
        if distance >= self._close_threshold:
            self._pending_since_ns = None
            return None
        self._state = PinchState.CLOSING
        self._pending_since_ns = timestamp_ns
        return self._update_closing(distance, timestamp_ns)

    def _update_closing(self, distance: float, timestamp_ns: int) -> PinchEvent | None:
        if distance >= self._close_threshold:
            self._state = PinchState.ARMED
            self._pending_since_ns = None
            return None
        assert self._pending_since_ns is not None
        if timestamp_ns - self._pending_since_ns < self._close_ns:
            return None
        onset_ns = self._pending_since_ns
        self._state = PinchState.PINCHED
        self._pending_since_ns = None
        self._pinched_since_ns = timestamp_ns
        return PinchEvent(PinchEventKind.INITIATED, onset_ns, timestamp_ns, distance)

    def _update_pinched(self, distance: float, timestamp_ns: int) -> PinchEvent | None:
        if distance <= self._release_threshold:
            self._pending_since_ns = None
            return None
        self._state = PinchState.RELEASING
        self._pending_since_ns = timestamp_ns
        return self._update_releasing(distance, timestamp_ns)

    def _update_releasing(self, distance: float, timestamp_ns: int) -> PinchEvent | None:
        if distance <= self._release_threshold:
            self._state = PinchState.PINCHED
            self._pending_since_ns = None
            return None
        assert self._pending_since_ns is not None
        if timestamp_ns - self._pending_since_ns < self._release_ns:
            return None
        onset_ns = self._pending_since_ns
        held_ns = None
        if self._pinched_since_ns is not None:
            held_ns = timestamp_ns - self._pinched_since_ns
        self._state = PinchState.AWAITING_REARM
        self._pending_since_ns = None
        self._pinched_since_ns = None
        return PinchEvent(
            PinchEventKind.RELEASED, onset_ns, timestamp_ns, distance, held_ns
        )

    def _update_awaiting_rearm(
        self, distance: float, timestamp_ns: int
    ) -> PinchEvent | None:
        if distance <= self._rearm_threshold:
            self._pending_since_ns = None
            return None
        if self._pending_since_ns is None:
            self._pending_since_ns = timestamp_ns
        if timestamp_ns - self._pending_since_ns < self._rearm_ns:
            return None
        self._state = PinchState.ARMED
        self._pending_since_ns = None
        return None

    def _suspend(self) -> None:
        if self._state is PinchState.CLOSING:
            self._state = PinchState.ARMED
        elif self._state is PinchState.RELEASING:
            self._state = PinchState.PINCHED
        self._pending_since_ns = None


class PinchGestureRecognizer:
    """Maps one pinch cycle to pointer mode entry, exit, or a click candidate.

    A pinch confirmed in ACTIVE emits ENTER_POINTER_MODE and is consumed, so its
    release cannot click. In POINTER_MODE a short release emits CLICK_CANDIDATE,
    and a pinch held for the long-pinch window emits EXIT_POINTER_MODE once and
    suppresses its release candidate.
    """

    def __init__(
        self,
        *,
        long_pinch_ms: int = 700,
        close_threshold: float = 0.22,
        release_threshold: float = 0.32,
        rearm_threshold: float = 0.40,
        close_confirm_ms: int = 100,
        release_confirm_ms: int = 100,
        rearm_confirm_ms: int = 300,
    ) -> None:
        self._machine = PinchStateMachine(
            close_threshold=close_threshold,
            release_threshold=release_threshold,
            rearm_threshold=rearm_threshold,
            close_confirm_ms=close_confirm_ms,
            release_confirm_ms=release_confirm_ms,
            rearm_confirm_ms=rearm_confirm_ms,
        )
        self._long_pinch_ns = long_pinch_ms * 1_000_000
        self._pinch_onset_ns: int | None = None
        self._pinch_confirmed_ns: int | None = None
        self._entry_pinch = False
        self._long_pinch = False

    @property
    def pinch_state(self) -> PinchState:
        return self._machine.state

    def reset(self) -> None:
        self._machine.reset()
        self._pinch_onset_ns = None
        self._pinch_confirmed_ns = None
        self._entry_pinch = False
        self._long_pinch = False

    def update(
        self,
        hand: HandRecord | None,
        state: InteractionState,
        timestamp_ns: int,
    ) -> SemanticEvent | None:
        event = self._machine.update(hand, timestamp_ns)
        confidence = 0.0 if hand is None else hand.confidence

        if event is not None and event.kind is PinchEventKind.INITIATED:
            self._pinch_onset_ns = event.onset_ns
            self._pinch_confirmed_ns = event.timestamp_ns
            self._entry_pinch = False
            self._long_pinch = False
            if state is InteractionState.ACTIVE:
                self._entry_pinch = True
                return self._semantic(
                    GestureAction.ENTER_POINTER_MODE,
                    Gesture.PINCH,
                    event.onset_ns,
                    timestamp_ns,
                    confidence,
                )
            return None

        if event is not None and event.kind is PinchEventKind.RELEASED:
            return self._on_release(event, state, confidence)

        if state is not InteractionState.POINTER_MODE:
            return None
        if not self._machine.is_closed or self._long_pinch:
            return None
        held_ns = self._machine.pinched_ns(timestamp_ns)
        if held_ns is None or held_ns < self._long_pinch_ns:
            return None
        onset_ns = self._pinch_onset_ns
        if onset_ns is None:
            onset_ns = timestamp_ns - held_ns
        self._long_pinch = True
        return self._semantic(
            GestureAction.EXIT_POINTER_MODE,
            Gesture.PINCH,
            onset_ns,
            timestamp_ns,
            confidence,
        )

    def _on_release(
        self, event: PinchEvent, state: InteractionState, confidence: float
    ) -> SemanticEvent | None:
        entry_pinch = self._entry_pinch
        long_pinch = self._long_pinch
        confirmed_ns = self._pinch_confirmed_ns
        onset_ns = self._pinch_onset_ns
        self._entry_pinch = False
        self._long_pinch = False
        self._pinch_onset_ns = None
        self._pinch_confirmed_ns = None
        if state is not InteractionState.POINTER_MODE:
            return None
        if entry_pinch or long_pinch:
            return None
        if confirmed_ns is not None and event.onset_ns - confirmed_ns >= self._long_pinch_ns:
            return self._semantic(
                GestureAction.EXIT_POINTER_MODE,
                Gesture.PINCH,
                event.onset_ns if onset_ns is None else onset_ns,
                event.timestamp_ns,
                confidence,
            )
        return self._semantic(
            GestureAction.CLICK_CANDIDATE,
            Gesture.PINCH_RELEASE,
            event.onset_ns,
            event.timestamp_ns,
            confidence,
        )

    @staticmethod
    def _semantic(
        action: GestureAction,
        gesture: Gesture,
        onset_ns: int,
        timestamp_ns: int,
        confidence: float,
    ) -> SemanticEvent:
        return SemanticEvent(action, gesture, onset_ns, timestamp_ns, confidence)
