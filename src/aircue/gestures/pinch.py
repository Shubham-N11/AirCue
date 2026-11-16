"""Pinch hysteresis state machine with confirmation windows."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

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
