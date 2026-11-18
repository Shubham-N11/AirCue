from __future__ import annotations

from dataclasses import replace

from aircue.app.runtime import AirCueRuntime, StartupComponent
from aircue.capture.types import (
    CaptureError,
    CaptureMode,
    CaptureOpenResult,
    CaptureUnavailableError,
    Frame,
)
from aircue.config.schema import Config
from aircue.presentation.adapter import AdapterResult, CommandPayload
from aircue.presentation.target import TargetSnapshot
from aircue.state.states import InteractionState


class FakeSource:
    def __init__(self, error: CaptureError | None = None) -> None:
        self.error = error
        self.requested: CaptureMode | None = None
        self.closed = False
        self._mode: CaptureMode | None = None

    @property
    def mode(self) -> CaptureMode | None:
        return self._mode

    def open(self, mode: CaptureMode) -> CaptureOpenResult:
        self.requested = mode
        if self.error is not None:
            raise self.error
        self._mode = mode
        return CaptureOpenResult(mode, mode, ())

    def read(self) -> Frame:
        raise NotImplementedError

    def close(self) -> None:
        self.closed = True
        self._mode = None


class FakeTracker:
    def __init__(self) -> None:
        self.closed = False

    def detect(self, frame: Frame):
        return ()

    def close(self) -> None:
        self.closed = True


class FakeAdapter:
    def snapshot(self) -> TargetSnapshot:
        return TargetSnapshot(captured_ns=0)

    def refresh(self) -> TargetSnapshot:
        return self.snapshot()

    def execute(self, payload: CommandPayload) -> AdapterResult:
        return AdapterResult()


def test_successful_initialization_reaches_idle() -> None:
    source = FakeSource()
    tracker = FakeTracker()
    runtime = AirCueRuntime(Config(), source=source, tracker=tracker, adapter=FakeAdapter())

    record = runtime.initialize()

    assert record.accepted is True
    assert record.resulting is InteractionState.IDLE
    assert runtime.state is InteractionState.IDLE
    assert runtime.failure is None
    assert source.requested == CaptureMode(1280, 720, 30)
    assert runtime.tracker is tracker
    assert runtime.worker is not None
    assert runtime.feedback.status.state is InteractionState.IDLE


def test_a_camera_failure_reaches_error_and_names_the_component() -> None:
    source = FakeSource(CaptureUnavailableError("no supported camera mode"))
    tracker = FakeTracker()
    runtime = AirCueRuntime(Config(), source=source, tracker=tracker, adapter=FakeAdapter())

    record = runtime.initialize()

    assert record.accepted is True
    assert record.resulting is InteractionState.ERROR
    assert runtime.state is InteractionState.ERROR
    assert runtime.failure is not None
    assert runtime.failure.component is StartupComponent.CAMERA
    assert record.reason.startswith("camera: ")
    assert "no supported camera mode" in record.reason
    assert source.closed is True
    assert tracker.closed is False


def test_a_tracker_failure_reaches_error_and_names_the_component() -> None:
    source = FakeSource()
    runtime = AirCueRuntime(Config(), source=source, adapter=FakeAdapter())

    record = runtime.initialize()

    assert record.resulting is InteractionState.ERROR
    assert runtime.failure is not None
    assert runtime.failure.component is StartupComponent.TRACKER
    assert record.reason.startswith("tracker: ")
    assert "model path is not configured" in record.reason
    assert source.closed is True


def test_close_releases_the_camera_and_tracker() -> None:
    source = FakeSource()
    tracker = FakeTracker()
    runtime = AirCueRuntime(Config(), source=source, tracker=tracker, adapter=FakeAdapter())
    runtime.initialize()

    runtime.close()

    assert source.closed is True
    assert tracker.closed is True
    assert runtime.source is None
    assert runtime.tracker is None
    assert runtime.worker is None


def test_a_failed_initialization_is_reported_in_feedback() -> None:
    runtime = AirCueRuntime(
        Config(), source=FakeSource(CaptureUnavailableError("busy")), adapter=FakeAdapter()
    )

    record = runtime.initialize()

    assert runtime.feedback.status.state is InteractionState.ERROR
    assert runtime.feedback.status.reason == record.reason


def test_the_capture_request_follows_the_tier2_profile() -> None:
    config = Config()
    tier = replace(config.hardware.tier2, width=960, height=540, max_fps=25.0)
    config = replace(config, hardware=replace(config.hardware, tier2=tier))
    source = FakeSource()
    runtime = AirCueRuntime(
        config, source=source, tracker=FakeTracker(), adapter=FakeAdapter()
    )

    runtime.initialize()

    assert source.requested == CaptureMode(960, 540, 25.0)
