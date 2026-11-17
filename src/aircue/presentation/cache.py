"""Target snapshot cache shared by the command worker and the state thread."""

from __future__ import annotations

from aircue.presentation.classify import classify_target
from aircue.presentation.discovery import DiscoveryResult
from aircue.presentation.target import TargetSnapshot


class TargetCache:
    """One immutable snapshot, refreshed by the worker and read by the state thread.

    A stale snapshot is reported as UNKNOWN with its original capture time, so
    the worker sends nothing and diagnostics still show when the target was seen.
    """

    def __init__(self, *, refresh_ms: int = 250, stale_ms: int = 1000) -> None:
        self._refresh_ns = refresh_ms * 1_000_000
        self._stale_ns = stale_ms * 1_000_000
        self._snapshot: TargetSnapshot | None = None

    def refresh(self, discovery: DiscoveryResult, now_ns: int) -> TargetSnapshot:
        snapshot = classify_target(discovery, now_ns)
        self._snapshot = snapshot
        return snapshot

    def snapshot(self, now_ns: int) -> TargetSnapshot:
        snapshot = self._snapshot
        if snapshot is None:
            return TargetSnapshot(captured_ns=now_ns)
        if not self._fresh(snapshot, now_ns):
            return TargetSnapshot(captured_ns=snapshot.captured_ns)
        return snapshot

    def is_fresh(self, now_ns: int) -> bool:
        snapshot = self._snapshot
        return snapshot is not None and self._fresh(snapshot, now_ns)

    def refresh_due(self, now_ns: int) -> bool:
        snapshot = self._snapshot
        return snapshot is None or now_ns - snapshot.captured_ns >= self._refresh_ns

    def _fresh(self, snapshot: TargetSnapshot, now_ns: int) -> bool:
        return now_ns - snapshot.captured_ns <= self._stale_ns
