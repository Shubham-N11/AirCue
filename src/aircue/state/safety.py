"""Tracking-loss and focus-loss handling for the state layer."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from aircue.state.transitions import TransitionTrigger


class TrackingStatus(StrEnum):
    TRACKED = "tracked"
    BRIEF_LOSS = "brief_loss"
    EXTENDED_LOSS = "extended_loss"
    TIMED_OUT = "timed_out"


@dataclass(frozen=True)
class TrackingReport:
    """What one frame means for presentation output."""

    status: TrackingStatus
    absent_ns: int
    output_frozen: bool
    trigger: TransitionTrigger | None = None


class SafetyMonitor:
    """Measures hand absence from its first frame and debounces focus loss.

    The absence clock starts at the first absent frame, which is the vision
    layer's first-absence timestamp when called once per frame. Output freezes
    immediately, and the timeout trigger fires once per absence episode so a
    continued gap cannot produce repeated transitions.
    """

    def __init__(self, *, freeze_ms: int = 300, idle_ms: int = 1000) -> None:
        self._freeze_ns = freeze_ms * 1_000_000
        self._idle_ns = idle_ms * 1_000_000
        self._first_absence_ns: int | None = None
        self._timed_out = False
        self._focused = True

    def tracking(self, present: bool, timestamp_ns: int) -> TrackingReport:
        if present:
            self._first_absence_ns = None
            self._timed_out = False
            return TrackingReport(TrackingStatus.TRACKED, 0, False)
        if self._first_absence_ns is None:
            self._first_absence_ns = timestamp_ns
        absent_ns = timestamp_ns - self._first_absence_ns

        if absent_ns > self._idle_ns:
            trigger = None
            if not self._timed_out:
                self._timed_out = True
                trigger = TransitionTrigger.TRACKING_TIMEOUT
            return TrackingReport(TrackingStatus.TIMED_OUT, absent_ns, True, trigger)
        if absent_ns >= self._freeze_ns:
            return TrackingReport(TrackingStatus.EXTENDED_LOSS, absent_ns, True)
        return TrackingReport(TrackingStatus.BRIEF_LOSS, absent_ns, True)

    def focus_changed(self, focused: bool) -> TransitionTrigger | None:
        """Report focus loss once per loss, not on every poll."""
        was_focused = self._focused
        self._focused = focused
        if was_focused and not focused:
            return TransitionTrigger.FOCUS_LOSS
        return None
