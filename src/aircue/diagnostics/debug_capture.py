"""Opt-in debug frame capture (design.md D6 privacy controls)."""

from __future__ import annotations

from pathlib import Path

import cv2

from aircue.capture.types import Frame


class DebugFrameStore:
    """Writes throttled JPEG frames only after the user opted in.

    A write failure disables capture for the rest of the session and returns
    the reason once, so an unwritable directory cannot stall the vision path.
    """

    def __init__(self, directory: str | Path, *, interval_ms: int = 1000) -> None:
        self.directory = Path(directory)
        self._interval_ns = interval_ms * 1_000_000
        self._last_write_ns: int | None = None
        self._failed = False

    def write(self, frame: Frame, timestamp_ns: int) -> str | None:
        """Store one JPEG per interval; returns the failure reason once."""
        if self._failed:
            return None
        if (
            self._last_write_ns is not None
            and timestamp_ns - self._last_write_ns < self._interval_ns
        ):
            return None
        self._last_write_ns = timestamp_ns
        try:
            self.directory.mkdir(parents=True, exist_ok=True)
            ok, encoded = cv2.imencode(".jpg", frame.image)
            if not ok:
                raise OSError("JPEG encoding failed")
            (self.directory / f"frame-{timestamp_ns}.jpg").write_bytes(
                encoded.tobytes()
            )
        except OSError as exc:
            self._failed = True
            return str(exc)
        return None
