"""Temporal confirmation, cooldown, and neutral re-arm for static gestures."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from aircue.gestures.vocabulary import Gesture


@dataclass(frozen=True)
class ConfirmedGesture:
    gesture: Gesture
    onset_ns: int
    onset_sequence: int
    timestamp_ns: int
    confidence: float


class TemporalValidator:
    """Confirms a continuously held gesture once, then requires a re-arm.

    A gesture confirms when it stays the candidate for its configured window.
    After confirmation, the same gesture stays disarmed until a different pose or
    neutral input has persisted for the re-arm window. Low-confidence frames cancel
    a pending confirmation and do not count toward re-arming.
    """

    def __init__(
        self,
        windows_ms: Mapping[Gesture, int],
        *,
        cooldown_ms: int = 500,
        rearm_ms: int = 300,
        confidence_threshold: float = 0.5,
    ) -> None:
        self._window_ns = {gesture: window * 1_000_000 for gesture, window in windows_ms.items()}
        self._cooldown_ns = cooldown_ms * 1_000_000
        self._rearm_ns = rearm_ms * 1_000_000
        self._confidence_threshold = confidence_threshold
        self._pending: Gesture | None = None
        self._pending_since_ns: int | None = None
        self._pending_since_sequence = 0
        self._pending_confidence = 0.0
        self._disarmed: Gesture | None = None
        self._different_since_ns: int | None = None
        self._last_confirmed_ns: dict[Gesture, int] = {}

    def reset(self) -> None:
        self._pending = None
        self._pending_since_ns = None
        self._pending_since_sequence = 0
        self._pending_confidence = 0.0
        self._disarmed = None
        self._different_since_ns = None
        self._last_confirmed_ns.clear()

    def update(
        self,
        candidate: Gesture | None,
        confidence: float,
        timestamp_ns: int,
        *,
        sequence: int = 0,
    ) -> ConfirmedGesture | None:
        low_confidence = candidate is not None and confidence < self._confidence_threshold
        if low_confidence:
            candidate = None

        if candidate is not self._pending:
            self._pending = candidate
            self._pending_since_ns = timestamp_ns if candidate is not None else None
            self._pending_since_sequence = sequence
        if candidate is not None:
            self._pending_confidence = confidence

        if self._disarmed is not None:
            if low_confidence:
                return None
            if candidate is not None and candidate is self._disarmed:
                self._different_since_ns = None
                return None
            if self._different_since_ns is None:
                self._different_since_ns = timestamp_ns
            if timestamp_ns - self._different_since_ns < self._rearm_ns:
                return None
            self._disarmed = None
            self._different_since_ns = None

        if candidate is None or self._pending_since_ns is None:
            return None
        window_ns = self._window_ns.get(candidate)
        if window_ns is None:
            raise ValueError(f"no confirmation window configured for {candidate}")
        if timestamp_ns - self._pending_since_ns < window_ns:
            return None

        last_confirmed = self._last_confirmed_ns.get(candidate)
        if last_confirmed is not None and timestamp_ns - last_confirmed < self._cooldown_ns:
            self._disarmed = candidate
            self._different_since_ns = None
            self._pending = None
            self._pending_since_ns = None
            return None

        onset_ns = self._pending_since_ns
        confirmed = ConfirmedGesture(
            gesture=candidate,
            onset_ns=onset_ns,
            onset_sequence=self._pending_since_sequence,
            timestamp_ns=timestamp_ns,
            confidence=self._pending_confidence,
        )
        self._last_confirmed_ns[candidate] = timestamp_ns
        self._disarmed = candidate
        self._different_since_ns = None
        self._pending = None
        self._pending_since_ns = None
        return confirmed
