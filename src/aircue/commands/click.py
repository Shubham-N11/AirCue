"""Double-click arbitration from design.md D9."""

from __future__ import annotations

from enum import StrEnum


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
