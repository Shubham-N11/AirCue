"""Presence and absence reporting. This module never changes application state."""

from __future__ import annotations

from aircue.vision.types import PresenceStatus


class PresenceReporter:
    def __init__(self) -> None:
        self._first_absence_ts_ns: int | None = None

    def observe(self, present: bool, timestamp_ns: int) -> PresenceStatus:
        if present:
            completed = (
                timestamp_ns - self._first_absence_ts_ns
                if self._first_absence_ts_ns is not None
                else None
            )
            self._first_absence_ts_ns = None
            return PresenceStatus(present=True, completed_absence_ns=completed)
        if self._first_absence_ts_ns is None:
            self._first_absence_ts_ns = timestamp_ns
        return PresenceStatus(
            present=False,
            first_absence_ts_ns=self._first_absence_ts_ns,
        )
