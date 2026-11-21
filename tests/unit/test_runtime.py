from __future__ import annotations

from dataclasses import replace

import pytest

from aircue.app.runtime import AirCueRuntime, StartupComponent
from aircue.capture.types import (
    CaptureError,
    CaptureMode,
    CaptureOpenResult,
    CaptureUnavailableError,
    Frame,
)
from aircue.config.schema import Config
from aircue.performance.resources import ProcessResources
from aircue.presentation.adapter import AdapterResult, CommandPayload
from aircue.presentation.target import TargetSnapshot
from aircue.state.feedback import StatusModel
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


class FakeResources:
    def __init__(self, *samples: ProcessResources) -> None:
        self._samples = list(samples)
        self.calls = 0

    def sample(self) -> ProcessResources:
        sample = self._samples[min(self.calls, len(self._samples) - 1)]
        self.calls += 1
        return sample


class RecordingIndicator:
    def __init__(self) -> None:
        self.updates: list[StatusModel] = []

    def update(self, status: StatusModel) -> None:
        self.updates.append(status)


def resource_runtime(
    *samples: ProcessResources,
    memory_ceiling_mb: int = 1024,
) -> tuple[AirCueRuntime, RecordingIndicator, FakeResources]:
    config = Config()
    config = replace(
        config,
        hardware=replace(
            config.hardware,
            memory_ceiling_mb=memory_ceiling_mb,
        ),
    )
    indicator = RecordingIndicator()
    resources = FakeResources(*samples)
    runtime = AirCueRuntime(
        config,
        source=FakeSource(),
        tracker=FakeTracker(),
        adapter=FakeAdapter(),
        indicator=indicator,
        resources=resources,
        key_down=lambda _key: False,
    )
    runtime.initialize()
    return runtime, indicator, resources


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
    assert tracker.closed is True


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


@pytest.mark.parametrize(
    ("profile", "expected"),
    [
        ("tier1", CaptureMode(640, 360, 15.0)),
        ("tier2", CaptureMode(1280, 720, 30.0)),
        ("tier3", CaptureMode(1280, 720, 60.0)),
    ],
)
def test_profile_changes_alter_the_capture_request_without_another_code_path(
    profile: str, expected: CaptureMode
) -> None:
    config = Config()
    config = replace(config, hardware=replace(config.hardware, profile=profile))
    source = FakeSource()
    runtime = AirCueRuntime(
        config, source=source, tracker=FakeTracker(), adapter=FakeAdapter()
    )

    runtime.initialize()

    assert source.requested == expected


def test_a_forced_frequency_reaches_the_capture_request() -> None:
    config = Config()
    config = replace(config, hardware=replace(config.hardware, processing_fps=24.0))
    source = FakeSource()
    runtime = AirCueRuntime(
        config, source=source, tracker=FakeTracker(), adapter=FakeAdapter()
    )

    runtime.initialize()

    assert source.requested == CaptureMode(1280, 720, 24.0)


def test_cpu_ceiling_disables_instrumentation_and_warns() -> None:
    runtime, indicator, _ = resource_runtime(
        ProcessResources(cpu_fraction=0.95, memory_bytes=64 * 1024 * 1024)
    )

    runtime.tick(0)

    assert runtime.instrument is False
    assert runtime.feedback.status.warning == "resource limit: cpu 95% >= 85%"
    assert indicator.updates[-1].warning is not None


def test_memory_ceiling_reports_megabytes() -> None:
    runtime, _, _ = resource_runtime(
        ProcessResources(cpu_fraction=0.10, memory_bytes=200 * 1024 * 1024),
        memory_ceiling_mb=100,
    )

    runtime.tick(0)

    assert runtime.instrument is False
    assert runtime.feedback.status.warning == "resource limit: memory 200 MB >= 100 MB"


def test_diagnostics_return_after_a_sustained_recovery_band() -> None:
    runtime, _, resources = resource_runtime(
        ProcessResources(cpu_fraction=0.95, memory_bytes=64 * 1024 * 1024),
        ProcessResources(cpu_fraction=0.50, memory_bytes=64 * 1024 * 1024),
    )

    runtime.tick(0)
    assert runtime.instrument is False

    runtime.tick(500_000_000)
    runtime.tick(2_499_999_999)
    assert runtime.instrument is False

    runtime.tick(3_000_000_000)
    assert runtime.instrument is True
    assert runtime.feedback.status.warning is None
    assert resources.calls == 4

    runtime.tick(3_100_000_000)
    assert resources.calls == 4


def test_safe_exit_stays_available_while_a_ceiling_is_exceeded() -> None:
    runtime, _, _ = resource_runtime(
        ProcessResources(cpu_fraction=0.99, memory_bytes=64 * 1024 * 1024)
    )
    runtime.tick(0)

    record = runtime.request_exit()

    assert record.accepted is True
    assert runtime.state is InteractionState.EXITING


def test_benchmarks_can_disable_resource_limits() -> None:
    runtime = AirCueRuntime(
        Config(),
        source=FakeSource(),
        tracker=FakeTracker(),
        adapter=FakeAdapter(),
        resource_limits=False,
    )

    assert runtime._resources is None
