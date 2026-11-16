"""Frame-source protocol."""

from __future__ import annotations

from typing import Protocol

from aircue.capture.types import CaptureMode, CaptureOpenResult, Frame


class FrameSource(Protocol):
    @property
    def mode(self) -> CaptureMode | None: ...

    def open(self, mode: CaptureMode) -> CaptureOpenResult: ...

    def read(self) -> Frame: ...

    def close(self) -> None: ...
