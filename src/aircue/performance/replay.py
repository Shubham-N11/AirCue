"""Deterministic replay benchmark from design.md D7.

A fixture is a `.npz` archive with BGR `images`, strictly increasing
`timestamps_ns`, and an optional `simulated_clock` flag. Replay drives those
frames through the runtime with a supplied tracker, so compute and command
metrics are measured without a camera; reports are labeled REPLAY and cannot
serve as live-camera evidence.
"""

from __future__ import annotations

import hashlib
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from aircue.app.runtime import AirCueRuntime
from aircue.capture.types import CaptureError, CaptureMode, CaptureOpenResult, Frame
from aircue.config.schema import Config, TierConfig
from aircue.performance.metrics import (
    AdapterMode,
    BenchmarkMode,
    PerformanceReport,
    PerformanceTargets,
    build_report,
)
from aircue.performance.timing import FrameTimings
from aircue.presentation.adapter import (
    AdapterResult,
    CommandPayload,
    PresentationAdapter,
)
from aircue.presentation.target import (
    ScreenRect,
    TargetKind,
    TargetSnapshot,
    capabilities_for,
)
from aircue.vision.tracker import HandTracker

DEFAULT_MONITOR = ScreenRect(0, 0, 1920, 1080)


class ReplayFixtureError(ValueError):
    """The fixture file is missing, malformed, or inconsistent."""


class ReplayError(RuntimeError):
    """The runtime could not start the replay."""


@dataclass(frozen=True)
class FrameFixture:
    """A loaded, hashed frame sequence."""

    images: tuple[np.ndarray, ...]
    timestamps_ns: tuple[int, ...]
    simulated_clock: bool
    fixture_hash: str

    @classmethod
    def load(cls, path: str | Path) -> FrameFixture:
        source = Path(path)
        try:
            raw = source.read_bytes()
        except OSError as exc:
            raise ReplayFixtureError(f"cannot read replay fixture: {exc}") from exc
        try:
            with np.load(source, allow_pickle=False) as data:
                images = np.asarray(data["images"])
                timestamps = np.asarray(data["timestamps_ns"], dtype=np.int64)
                simulated = (
                    bool(int(data["simulated_clock"]))
                    if "simulated_clock" in data
                    else True
                )
        except Exception as exc:
            raise ReplayFixtureError(f"invalid replay fixture: {exc}") from exc

        if images.ndim == 3:
            images = images[..., np.newaxis].repeat(3, axis=-1)
        if images.ndim != 4 or images.shape[-1] != 3:
            raise ReplayFixtureError("images must have shape (frames, height, width, 3)")
        if len(images) == 0:
            raise ReplayFixtureError("fixture has no frames")
        if timestamps.shape != (len(images),):
            raise ReplayFixtureError("timestamps_ns must have one entry per frame")
        if any(
            later <= earlier
            for earlier, later in zip(timestamps, timestamps[1:], strict=False)
        ):
            raise ReplayFixtureError("timestamps_ns must be strictly increasing")

        return cls(
            images=tuple(np.ascontiguousarray(image, dtype=np.uint8) for image in images),
            timestamps_ns=tuple(int(value) for value in timestamps),
            simulated_clock=simulated,
            fixture_hash=hashlib.sha256(raw).hexdigest(),
        )


class NoopAdapter:
    """Accepts validated commands without synthesizing input."""

    def __init__(
        self,
        *,
        kind: TargetKind = TargetKind.NORMAL_SLIDESHOW,
        monitor_bounds: ScreenRect = DEFAULT_MONITOR,
    ) -> None:
        self._snapshot = TargetSnapshot(
            captured_ns=0,
            kind=kind,
            capabilities=capabilities_for(kind),
            monitor_bounds=monitor_bounds,
        )
        self.executed: list[CommandPayload] = []

    def snapshot(self) -> TargetSnapshot:
        return self._snapshot

    def refresh(self) -> TargetSnapshot:
        return self._snapshot

    def execute(self, payload: CommandPayload) -> AdapterResult:
        self.executed.append(payload)
        return AdapterResult()


class _ReplaySource:
    """Satisfies initialize without opening a camera; replay never reads it."""

    def __init__(self) -> None:
        self._mode: CaptureMode | None = None

    @property
    def mode(self) -> CaptureMode | None:
        return self._mode

    def open(self, mode: CaptureMode) -> CaptureOpenResult:
        self._mode = mode
        return CaptureOpenResult(mode, mode, ())

    def read(self) -> Frame:
        raise CaptureError("replay fixture has no camera")

    def close(self) -> None:
        self._mode = None


class _SimulatedClock:
    def __init__(self) -> None:
        self.now_ns = 0

    def __call__(self) -> int:
        return self.now_ns


def _selected_tier(config: Config) -> TierConfig:
    profile = config.hardware.profile
    if profile == "auto":
        return config.hardware.tier2
    return getattr(config.hardware, profile)


def run_replay(
    fixture: FrameFixture,
    config: Config,
    *,
    tracker: HandTracker,
    adapter: PresentationAdapter | None = None,
    instrument: bool = True,
    targets: PerformanceTargets | None = None,
) -> PerformanceReport:
    """Drive one fixture pass and return its REPLAY report."""
    simulated = _SimulatedClock() if fixture.simulated_clock else None
    clock: Callable[[], int] = time.monotonic_ns if simulated is None else simulated
    runtime = AirCueRuntime(
        config,
        source=_ReplaySource(),
        tracker=tracker,
        adapter=adapter or NoopAdapter(),
        clock_ns=clock,
        key_down=lambda _key: False,
        instrument=instrument,
    )
    try:
        startup = runtime.initialize()
        if not startup.accepted:
            raise ReplayError(f"replay startup failed: {startup.reason}")
        if runtime.worker is None:
            raise ReplayError("replay command worker did not start")
        runtime.worker.start()

        for sequence, (image, timestamp_ns) in enumerate(
            zip(fixture.images, fixture.timestamps_ns, strict=True), start=1
        ):
            if simulated is not None:
                simulated.now_ns = timestamp_ns
                frame_ts = timestamp_ns
            else:
                frame_ts = clock()
            timings = FrameTimings() if instrument else None
            runtime.process_frame(Frame(image, frame_ts, sequence, timings))
            runtime.tick(frame_ts)

        _drain_worker(runtime)
        return build_report(
            runtime.metrics,
            targets
            or PerformanceTargets.from_tier(
                _selected_tier(config), basis=config.hardware.profile
            ),
            benchmark_mode=BenchmarkMode.REPLAY,
            adapter_mode=AdapterMode.NOOP,
            fixture_hash=fixture.fixture_hash,
            simulated_clock=fixture.simulated_clock,
            now_ns=clock(),
        )
    finally:
        runtime.close()


def _drain_worker(runtime: AirCueRuntime) -> None:
    worker = runtime.worker
    if worker is None:
        return
    deadline = time.monotonic() + 1.0
    while worker.pending and time.monotonic() < deadline:
        time.sleep(0.001)
    time.sleep(0.005)
    runtime.tick(runtime.clock_ns())
    runtime.tick(runtime.clock_ns())
