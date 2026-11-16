import numpy as np
import pytest

from aircue.capture import (
    CaptureFailureError,
    CaptureMode,
    CaptureUnavailableError,
    OpenCvCameraSource,
)


class FakeCapture:
    def __init__(self, supported: set[tuple[int, int, int]], default=(640, 360, 30)) -> None:
        self.supported = supported
        self.width, self.height, self.fps = default
        self.opened = True
        self.released = False
        self._pending: dict[int, float] = {}

    def isOpened(self) -> bool:  # noqa: N802 - mirrors the cv2 API
        return self.opened and not self.released

    def set(self, prop: int, value: float) -> bool:
        self._pending[prop] = value
        return True

    def get(self, prop: int) -> float:
        import cv2

        if prop in (cv2.CAP_PROP_FRAME_WIDTH, cv2.CAP_PROP_FRAME_HEIGHT, cv2.CAP_PROP_FPS):
            if len(self._pending) >= 3:
                width = int(self._pending[cv2.CAP_PROP_FRAME_WIDTH])
                height = int(self._pending[cv2.CAP_PROP_FRAME_HEIGHT])
                fps = round(self._pending[cv2.CAP_PROP_FPS])
                if (width, height, fps) in self.supported:
                    self.width, self.height, self.fps = width, height, fps
                self._pending.clear()
            if prop == cv2.CAP_PROP_FRAME_WIDTH:
                return float(self.width)
            if prop == cv2.CAP_PROP_FRAME_HEIGHT:
                return float(self.height)
            return float(self.fps)
        return 0.0

    def read(self) -> tuple[bool, object]:
        return True, np.zeros((self.height, self.width, 3), dtype=np.uint8)

    def release(self) -> None:
        self.released = True


def make_factory(capture: FakeCapture):
    return lambda _index: capture


def test_requested_mode_is_used_when_supported() -> None:
    camera = FakeCapture({(640, 360, 30)})
    source = OpenCvCameraSource(factory=make_factory(camera))
    result = source.open(CaptureMode(640, 360, 30))
    assert result.mode == CaptureMode(640, 360, 30)
    assert result.fallback_used is False
    assert len(result.attempts) == 1
    assert source.mode == CaptureMode(640, 360, 30)


def test_unsupported_mode_falls_back_to_nearest_supported() -> None:
    camera = FakeCapture({(640, 360, 30)})
    source = OpenCvCameraSource(factory=make_factory(camera))
    result = source.open(CaptureMode(1280, 720, 30))
    assert result.mode == CaptureMode(640, 360, 30)
    assert result.fallback_used is True
    assert len(result.attempts) > 1


def test_no_supported_configuration_raises() -> None:
    camera = FakeCapture(set())
    camera.opened = False
    source = OpenCvCameraSource(factory=make_factory(camera))
    with pytest.raises(CaptureUnavailableError):
        source.open(CaptureMode(640, 360, 30))


def test_capture_failure_after_open_raises() -> None:
    camera = FakeCapture({(640, 360, 30)})
    source = OpenCvCameraSource(factory=make_factory(camera))
    source.open(CaptureMode(640, 360, 30))

    def fail() -> tuple[bool, object]:
        return False, None

    camera.read = fail  # type: ignore[method-assign]
    with pytest.raises(CaptureFailureError):
        source.read()


def test_read_before_open_raises() -> None:
    source = OpenCvCameraSource(factory=make_factory(FakeCapture({(640, 360, 30)})))
    with pytest.raises(CaptureFailureError):
        source.read()


def test_frames_carry_monotonic_timestamps_and_sequence() -> None:
    camera = FakeCapture({(640, 360, 30)})
    ticks = iter([100, 200])
    source = OpenCvCameraSource(factory=make_factory(camera), clock_ns=lambda: next(ticks))
    source.open(CaptureMode(640, 360, 30))
    first = source.read()
    second = source.read()
    assert (first.capture_ts_ns, first.sequence) == (100, 1)
    assert (second.capture_ts_ns, second.sequence) == (200, 2)


def test_close_releases_capture() -> None:
    camera = FakeCapture({(640, 360, 30)})
    source = OpenCvCameraSource(factory=make_factory(camera))
    source.open(CaptureMode(640, 360, 30))
    source.close()
    assert camera.released is True
    assert source.mode is None
