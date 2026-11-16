"""Primary-hand selection with identity continuity across frames."""

from __future__ import annotations

import math
from dataclasses import dataclass

from aircue.vision.types import WRIST, HandObservation


@dataclass(frozen=True)
class PrimarySelection:
    observation: HandObservation | None
    stable_id: int | None
    suppress_recognition: bool
    switched: bool = False


class PrimaryHandSelector:
    def __init__(self, *, switch_window_ms: int, match_distance: float) -> None:
        self._switch_window_ns = switch_window_ms * 1_000_000
        self._match_distance = match_distance
        self._stable_id: int | None = None
        self._last_wrist: tuple[float, float] | None = None
        self._last_handedness: str | None = None
        self._last_seen_ts_ns: int | None = None
        self._absence_since_ns: int | None = None
        self._next_stable_id = 1

    def update(
        self, observations: tuple[HandObservation, ...], timestamp_ns: int
    ) -> PrimarySelection:
        if not observations:
            self._mark_absent(timestamp_ns)
            return PrimarySelection(None, self._stable_id, suppress_recognition=True)

        if self._stable_id is None and self._last_wrist is None:
            chosen = max(observations, key=lambda item: item.confidence)
            self._stable_id = 0
            self._remember(chosen, timestamp_ns)
            return PrimarySelection(chosen, self._stable_id, suppress_recognition=False)

        matched = self._match_primary(observations)
        if matched is not None:
            was_absent = self._absence_since_ns is not None
            self._absence_since_ns = None
            self._remember(matched, timestamp_ns)
            return PrimarySelection(matched, self._stable_id, suppress_recognition=was_absent)

        elapsed = self._absence_elapsed_ns(timestamp_ns)
        if elapsed is not None and elapsed >= self._switch_window_ns:
            chosen = max(observations, key=lambda item: item.confidence)
            self._stable_id = self._next_stable_id
            self._next_stable_id += 1
            self._absence_since_ns = None
            self._remember(chosen, timestamp_ns)
            return PrimarySelection(
                chosen, self._stable_id, suppress_recognition=True, switched=True
            )

        self._mark_absent(timestamp_ns)
        return PrimarySelection(None, self._stable_id, suppress_recognition=True)

    def _match_primary(
        self, observations: tuple[HandObservation, ...]
    ) -> HandObservation | None:
        if self._last_wrist is None:
            return None
        candidates: list[tuple[float, HandObservation]] = []
        for observation in observations:
            if len(observation.landmarks) <= WRIST:
                continue
            if self._last_handedness and observation.handedness != self._last_handedness:
                continue
            wrist = observation.landmarks[WRIST]
            distance = math.hypot(wrist.x - self._last_wrist[0], wrist.y - self._last_wrist[1])
            if distance <= self._match_distance:
                candidates.append((distance, observation))
        if not candidates:
            return None
        return min(candidates, key=lambda item: item[0])[1]

    def _remember(self, observation: HandObservation, timestamp_ns: int) -> None:
        if len(observation.landmarks) > WRIST:
            wrist = observation.landmarks[WRIST]
            self._last_wrist = (wrist.x, wrist.y)
        self._last_handedness = observation.handedness
        self._last_seen_ts_ns = timestamp_ns

    def _mark_absent(self, timestamp_ns: int) -> None:
        if self._absence_since_ns is None:
            self._absence_since_ns = (
                self._last_seen_ts_ns if self._last_seen_ts_ns is not None else timestamp_ns
            )

    def _absence_elapsed_ns(self, timestamp_ns: int) -> int | None:
        if self._absence_since_ns is None:
            return None
        return max(0, timestamp_ns - self._absence_since_ns)
