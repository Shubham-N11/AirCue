"""OpenCV-backed camera source with nearest-supported-mode fallback."""

from __future__ import annotations

import time
from collections.abc import Callable, Iterator
from typing import Any

import cv2
import numpy as np

from aircue.capture.types import (
    CaptureAttempt,
    CaptureFailureError,
    CaptureMode,
    CaptureOpenResult,
    CaptureUnavailableError,
    Frame,
)

CaptureFactory = Callable[[int], Any]


def candidate_modes(requested: CaptureMode) -> Iterator[CaptureMode]:
    """Yield the requested mode, then progressively smaller fallbacks."""
    seen: set[tuple[int, int, int]] = set()

    def emit(width: int, height: int, fps: float) -> CaptureMode | None:
        width = max(160, (width // 2) * 2)
        height = max(120, (height // 2) * 2)
        rate = max(1, round(fps))
        key = (width, height, rate)
        if key in seen:
            return None
        seen.add(key)
        return CaptureMode(width, height, float(rate))

    for scale in (1.0, 0.75, 0.5):
        for rate_scale in (1.0, 0.5):
            candidate = emit(
                int(requested.width * scale),
                int(requested.height * scale),
                requested.fps * rate_scale,
            )
            if candidate is not None:
                yield candidate
    floor = emit(320, 240, 15)
    if floor is not None:
        yield floor


class OpenCvCameraSource:
    def __init__(
        self,
        device_index: int = 0,
        *,
        factory: CaptureFactory | None = None,
        clock_ns: Callable[[], int] = time.monotonic_ns,
    ) -> None:
        self._device_index = device_index
        self._factory = factory or cv2.VideoCapture
        self._clock_ns = clock_ns
        self._capture: Any | None = None
        self._mode: CaptureMode | None = None
        self._sequence = 0

    @property
    def mode(self) -> CaptureMode | None:
        return self._mode

    def open(self, requested: CaptureMode) -> CaptureOpenResult:
        self.close()
        attempts: list[CaptureAttempt] = []
        best: tuple[Any, CaptureMode] | None = None

        for candidate in candidate_modes(requested):
            capture = self._factory(self._device_index)
            if not capture.isOpened():
                attempts.append(
                    CaptureAttempt(candidate, opened=False, reason="device unavailable")
                )
                capture.release()
                continue

            capture.set(cv2.CAP_PROP_FRAME_WIDTH, candidate.width)
            capture.set(cv2.CAP_PROP_FRAME_HEIGHT, candidate.height)
            capture.set(cv2.CAP_PROP_FPS, candidate.fps)
            actual = self._actual_mode(capture, candidate)
            attempts.append(CaptureAttempt(candidate, opened=True))

            if _same_mode(actual, candidate):
                if best is not None:
                    best[0].release()
                self._capture = capture
                self._mode = actual
                self._sequence = 0
                return CaptureOpenResult(actual, requested, tuple(attempts))

            if best is None:
                best = (capture, actual)
            else:
                capture.release()

        if best is None:
            raise CaptureUnavailableError(
                f"no supported camera mode for "
                f"{requested.width}x{requested.height}@{requested.fps:g}"
            )
        self._capture, self._mode = best
        self._sequence = 0
        return CaptureOpenResult(self._mode, requested, tuple(attempts))

    def read(self) -> Frame:
        if self._capture is None:
            raise CaptureFailureError("camera is not open")
        ok, image = self._capture.read()
        if not ok or image is None:
            raise CaptureFailureError("camera frame read failed")
        self._sequence += 1
        return Frame(
            image=np.asarray(image),
            capture_ts_ns=self._clock_ns(),
            sequence=self._sequence,
        )

    def close(self) -> None:
        if self._capture is not None:
            self._capture.release()
        self._capture = None
        self._mode = None
        self._sequence = 0

    @staticmethod
    def _actual_mode(capture: Any, candidate: CaptureMode) -> CaptureMode:
        width = int(round(capture.get(cv2.CAP_PROP_FRAME_WIDTH)))
        height = int(round(capture.get(cv2.CAP_PROP_FRAME_HEIGHT)))
        fps = float(capture.get(cv2.CAP_PROP_FPS))
        if width <= 0 or height <= 0:
            return candidate
        return CaptureMode(width, height, fps if fps > 0 else candidate.fps)


def _same_mode(left: CaptureMode, right: CaptureMode) -> bool:
    return (
        left.width == right.width
        and left.height == right.height
        and abs(left.fps - right.fps) <= 0.5
    )
