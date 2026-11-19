"""Deterministic replay: fixture identity, frame order, and report labeling."""

from __future__ import annotations

import hashlib
from pathlib import Path

import numpy as np
import pytest

from aircue.config.schema import Config
from aircue.performance.metrics import AdapterMode, BenchmarkMode
from aircue.performance.replay import (
    FrameFixture,
    ReplayFixtureError,
    run_replay,
)
from aircue.performance.timing import Stage, measure

MS = 1_000_000


def write_fixture(
    path: Path,
    *,
    frames: int = 3,
    simulated: int | None = None,
    images: np.ndarray | None = None,
    timestamps: list[int] | None = None,
) -> Path:
    if images is None:
        images = np.zeros((frames, 6, 8, 3), dtype=np.uint8)
    if timestamps is None:
        timestamps = [index * 100 * MS for index in range(frames)]
    payload: dict[str, object] = {
        "images": images,
        "timestamps_ns": np.asarray(timestamps, dtype=np.int64),
    }
    if simulated is not None:
        payload["simulated_clock"] = np.asarray(simulated, dtype=np.int8)
    np.savez(path, **payload)
    return path


class StageRecordingTracker:
    """Instruments like the real tracker without loading a model."""

    def __init__(self) -> None:
        self.timestamps: list[int] = []
        self.closed = False

    def detect(self, frame):
        self.timestamps.append(frame.capture_ts_ns)
        with measure(frame.timings, Stage.PREPROCESSING):
            np.zeros((2, 2, 3), dtype=np.uint8)
        with measure(frame.timings, Stage.INFERENCE):
            sum(range(16))
        return ()

    def close(self) -> None:
        self.closed = True


def test_fixture_identity_is_the_hash_of_the_file_bytes(tmp_path: Path) -> None:
    path = write_fixture(tmp_path / "fixture.npz")

    fixture = FrameFixture.load(path)

    assert fixture.fixture_hash == hashlib.sha256(path.read_bytes()).hexdigest()
    assert fixture.timestamps_ns == (0, 100 * MS, 200 * MS)
    assert fixture.simulated_clock is True
    assert len(fixture.images) == 3


def test_a_grayscale_fixture_is_expanded_to_three_channels(tmp_path: Path) -> None:
    images = np.zeros((2, 5, 4), dtype=np.uint8)
    path = write_fixture(
        tmp_path / "gray.npz", frames=2, images=images, timestamps=[0, MS]
    )

    fixture = FrameFixture.load(path)

    assert fixture.images[0].shape == (5, 4, 3)


@pytest.mark.parametrize(
    "payload",
    [
        {"images": np.zeros((1, 4, 4, 3), dtype=np.uint8)},
        {
            "images": np.zeros((0, 4, 4, 3), dtype=np.uint8),
            "timestamps_ns": np.asarray([], dtype=np.int64),
        },
        {
            "images": np.zeros((2, 4, 4, 3), dtype=np.uint8),
            "timestamps_ns": np.asarray([MS], dtype=np.int64),
        },
        {
            "images": np.zeros((2, 4, 4, 3), dtype=np.uint8),
            "timestamps_ns": np.asarray([2 * MS, MS], dtype=np.int64),
        },
    ],
)
def test_malformed_fixtures_fail_cleanly(
    tmp_path: Path, payload: dict[str, object]
) -> None:
    path = tmp_path / "bad.npz"
    np.savez(path, **payload)

    with pytest.raises(ReplayFixtureError):
        FrameFixture.load(path)


def test_a_missing_fixture_fails_cleanly(tmp_path: Path) -> None:
    with pytest.raises(ReplayFixtureError, match="cannot read"):
        FrameFixture.load(tmp_path / "missing.npz")


def test_replay_processes_every_frame_in_order_and_labels_its_report(
    tmp_path: Path,
) -> None:
    fixture = FrameFixture.load(write_fixture(tmp_path / "fixture.npz"))
    tracker = StageRecordingTracker()

    report = run_replay(fixture, Config(), tracker=tracker)

    assert report.benchmark_mode is BenchmarkMode.REPLAY
    assert report.adapter_mode is AdapterMode.NOOP
    assert report.fixture_hash == fixture.fixture_hash
    assert report.simulated_clock is True
    assert tracker.timestamps == list(fixture.timestamps_ns)
    assert tracker.closed is True
    assert report.frame_rate_fps == pytest.approx(10.0)
    by_name = {metric.name: metric for metric in report.metrics}
    for name in ("preprocessing", "inference", "classification", "recognition_compute"):
        assert name in by_name
    assert report.slowest_stage in by_name


def test_disabled_instrumentation_still_processes_frames(tmp_path: Path) -> None:
    fixture = FrameFixture.load(write_fixture(tmp_path / "fixture.npz"))
    tracker = StageRecordingTracker()

    report = run_replay(fixture, Config(), tracker=tracker, instrument=False)

    assert tracker.timestamps == list(fixture.timestamps_ns)
    assert report.metrics == ()
    assert report.sample_count == 0
    assert report.passed is None


def test_a_real_clock_fixture_is_reported_as_not_simulated(tmp_path: Path) -> None:
    fixture = FrameFixture.load(
        write_fixture(tmp_path / "fixture.npz", simulated=0)
    )
    tracker = StageRecordingTracker()

    report = run_replay(fixture, Config(), tracker=tracker)

    assert report.simulated_clock is False
    assert len(tracker.timestamps) == len(fixture.timestamps_ns)
