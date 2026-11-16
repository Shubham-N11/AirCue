"""Open-palm wrist rotation detection with neutral reference and bounded repeats."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from enum import StrEnum

from aircue.gestures.classifiers import is_open_palm
from aircue.gestures.geometry import angle_from_neutral, to_user_perspective_angle
from aircue.vision.types import HandRecord


class RotationDirection(StrEnum):
    CLOCKWISE = "clockwise"
    COUNTERCLOCKWISE = "counterclockwise"


@dataclass(frozen=True)
class RotationEvent:
    direction: RotationDirection
    delta_deg: float
    onset_sequence: int
    timestamp_ns: int
    confidence: float


class RotationDetector:
    """Detects one rotation event per deliberate displacement from neutral.

    The neutral reference is the user-perspective wrist angle when an open palm is
    first seen or returns inside the neutral band. Positive deltas are clockwise from
    the user's perspective.
    """

    def __init__(
        self,
        *,
        activation_deg: float = 25.0,
        neutral_band_deg: float = 8.0,
        continuous_enabled: bool = False,
        repeat_step_deg: float = 30.0,
        repeat_interval_ms: int = 400,
        max_events_per_second: float = 2.0,
    ) -> None:
        self._activation_deg = activation_deg
        self._neutral_band_deg = neutral_band_deg
        self._continuous_enabled = continuous_enabled
        self._repeat_step_deg = repeat_step_deg
        self._repeat_interval_ns = repeat_interval_ms * 1_000_000
        self._max_events_per_second = max_events_per_second
        self._event_times: deque[int] = deque()
        self._neutral_deg: float | None = None
        self._active = False
        self._direction: RotationDirection | None = None
        self._next_repeat_deg: float | None = None
        self._last_event_ts_ns: int | None = None

    def reset(self) -> None:
        """Forget the neutral reference and all repeat state."""
        self._event_times.clear()
        self._neutral_deg = None
        self._active = False
        self._direction = None
        self._next_repeat_deg = None
        self._last_event_ts_ns = None

    def update(
        self,
        hand: HandRecord | None,
        timestamp_ns: int,
        *,
        sequence: int = 0,
    ) -> RotationEvent | None:
        angle = None if hand is None else hand.features.wrist_angle_deg
        if hand is None or angle is None or not is_open_palm(hand):
            self.reset()
            return None

        user_angle = to_user_perspective_angle(angle)
        if self._neutral_deg is None:
            self._neutral_deg = user_angle
            return None

        delta = angle_from_neutral(user_angle, self._neutral_deg)
        if abs(delta) <= self._neutral_band_deg:
            self._neutral_deg = user_angle
            self._active = False
            self._direction = None
            self._next_repeat_deg = None
            return None

        direction = (
            RotationDirection.CLOCKWISE if delta > 0 else RotationDirection.COUNTERCLOCKWISE
        )
        if not self._active or direction is not self._direction:
            if abs(delta) < self._activation_deg:
                return None
            return self._emit(direction, delta, timestamp_ns, sequence, hand.confidence)

        if not self._continuous_enabled or self._next_repeat_deg is None:
            return None
        if abs(delta) < self._next_repeat_deg:
            return None
        if (
            self._last_event_ts_ns is not None
            and timestamp_ns - self._last_event_ts_ns < self._repeat_interval_ns
        ):
            return None

        self._prune_event_times(timestamp_ns)
        if len(self._event_times) >= self._max_events_per_second:
            return None
        return self._emit(direction, delta, timestamp_ns, sequence, hand.confidence)

    def _emit(
        self,
        direction: RotationDirection,
        delta: float,
        timestamp_ns: int,
        sequence: int,
        confidence: float,
    ) -> RotationEvent:
        self._active = True
        self._direction = direction
        self._last_event_ts_ns = timestamp_ns
        self._event_times.append(timestamp_ns)
        self._next_repeat_deg = (
            abs(delta) + self._repeat_step_deg if self._continuous_enabled else None
        )
        return RotationEvent(direction, delta, sequence, timestamp_ns, confidence)

    def _prune_event_times(self, timestamp_ns: int) -> None:
        while self._event_times and timestamp_ns - self._event_times[0] >= 1_000_000_000:
            self._event_times.popleft()
