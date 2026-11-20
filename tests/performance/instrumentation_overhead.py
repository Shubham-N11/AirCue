"""Instrumentation-overhead protocol from design.md D7. Not a pytest gate.

Alternates instrumentation-enabled and instrumentation-disabled replay blocks
over the same deterministic fixture and times the processing loop externally.
Defaults are the required protocol: 10 s warm-up and five 60 s blocks per
condition. The workload is synthetic and identical in both conditions, so the
reported delta is instrumentation overhead, not inference performance.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import platform
import statistics
import tempfile
import time
from pathlib import Path

import cv2
import numpy as np

from aircue.app.runtime import AirCueRuntime
from aircue.capture.types import Frame
from aircue.config.schema import Config
from aircue.performance.metrics import percentile_ns
from aircue.performance.replay import FrameFixture, NoopAdapter, _ReplaySource
from aircue.performance.timing import FrameTimings, Stage, measure

TARGET_MS = 2.0
BLOCKS = 5
WARMUP_SECONDS = 10.0
BLOCK_SECONDS = 60.0
T95_DF4 = 2.7764451051977987
FIXTURE_FRAMES = 8
FRAME_WIDTH = 640
FRAME_HEIGHT = 360


class SyntheticTracker:
    """Does fixed cv2 work and records the same stage spans as the real tracker."""

    def detect(self, frame: Frame) -> tuple[()]:
        with measure(frame.timings, Stage.PREPROCESSING):
            rgb = cv2.cvtColor(frame.image, cv2.COLOR_BGR2RGB)
        with measure(frame.timings, Stage.INFERENCE):
            cv2.GaussianBlur(rgb, (5, 5), 0)
        with measure(frame.timings, Stage.LANDMARK_PROCESSING):
            pass
        return ()

    def close(self) -> None:
        pass


def synthetic_fixture(directory: Path) -> FrameFixture:
    rng = np.random.default_rng(20261119)
    images = rng.integers(
        0, 256, (FIXTURE_FRAMES, FRAME_HEIGHT, FRAME_WIDTH, 3), dtype=np.uint8
    )
    path = directory / "overhead-fixture.npz"
    np.savez(
        path,
        images=images,
        timestamps_ns=np.arange(FIXTURE_FRAMES, dtype=np.int64) * 33_000_000,
        simulated_clock=np.asarray(0, dtype=np.int8),
    )
    return FrameFixture.load(path)


def run_block(
    fixture: FrameFixture, config: Config, *, instrument: bool, seconds: float
) -> list[int]:
    """Return externally timed per-frame loop durations for one block."""
    runtime = AirCueRuntime(
        config,
        source=_ReplaySource(),
        tracker=SyntheticTracker(),
        adapter=NoopAdapter(),
        clock_ns=time.monotonic_ns,
        key_down=lambda _key: False,
        instrument=instrument,
    )
    samples: list[int] = []
    sequence = 0
    try:
        startup = runtime.initialize()
        if not startup.accepted or runtime.worker is None:
            raise RuntimeError(f"replay startup failed: {startup.reason}")
        runtime.worker.start()
        deadline = time.perf_counter() + seconds
        while time.perf_counter() < deadline:
            for image in fixture.images:
                timestamp_ns = time.monotonic_ns()
                timings = FrameTimings() if instrument else None
                sequence += 1
                started_ns = time.perf_counter_ns()
                runtime.process_frame(Frame(image, timestamp_ns, sequence, timings))
                runtime.tick(timestamp_ns)
                samples.append(time.perf_counter_ns() - started_ns)
                if time.perf_counter() >= deadline:
                    break
    finally:
        runtime.close()
    if not samples:
        raise RuntimeError("block produced no frames")
    return samples


def block_summary(samples: list[int]) -> dict[str, float]:
    return {
        "frames": float(len(samples)),
        "p50_ms": percentile_ns(samples, 50) / 1_000_000,
        "p95_ms": percentile_ns(samples, 95) / 1_000_000,
    }


def mean_ci95(values: list[float]) -> list[float]:
    mean = statistics.fmean(values)
    if len(values) < 2:
        return [mean, mean]
    half = T95_DF4 * statistics.stdev(values) / math.sqrt(len(values))
    return [mean - half, mean + half]


def measure_condition(
    fixture: FrameFixture, config: Config, *, instrument: bool, seconds: float
) -> list[int]:
    return run_block(fixture, config, instrument=instrument, seconds=seconds)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--warmup-seconds", type=float, default=WARMUP_SECONDS)
    parser.add_argument("--block-seconds", type=float, default=BLOCK_SECONDS)
    parser.add_argument("--json", metavar="PATH", help="write the full report here")
    args = parser.parse_args()

    config = Config()
    with tempfile.TemporaryDirectory(prefix="aircue-overhead-") as directory:
        fixture = synthetic_fixture(Path(directory))
        enabled_blocks: list[list[int]] = []
        disabled_blocks: list[list[int]] = []

        measure_condition(fixture, config, instrument=True, seconds=args.warmup_seconds)
        measure_condition(fixture, config, instrument=False, seconds=args.warmup_seconds)

        for index in range(BLOCKS):
            first, second = (
                (False, True) if index % 2 == 0 else (True, False)
            )
            for instrument in (first, second):
                samples = measure_condition(
                    fixture, config, instrument=instrument, seconds=args.block_seconds
                )
                (enabled_blocks if instrument else disabled_blocks).append(samples)

        enabled = [block_summary(samples) for samples in enabled_blocks]
        disabled = [block_summary(samples) for samples in disabled_blocks]
        p50_deltas = [
            enabled[i]["p50_ms"] - disabled[i]["p50_ms"] for i in range(BLOCKS)
        ]
        p95_deltas = [
            enabled[i]["p95_ms"] - disabled[i]["p95_ms"] for i in range(BLOCKS)
        ]
        pooled = [
            enabled_samples[j] - disabled_samples[j]
            for enabled_samples, disabled_samples in zip(
                enabled_blocks, disabled_blocks, strict=True
            )
            for j in range(min(len(enabled_samples), len(disabled_samples)))
        ]
        median_delta_ms = percentile_ns(pooled, 50) / 1_000_000
        p95_delta_ms = percentile_ns(pooled, 95) / 1_000_000

        report = {
            "host": {
                "platform": platform.platform(),
                "processor": platform.processor(),
                "cpu_count": os.cpu_count(),
                "python": platform.python_version(),
            },
            "protocol": {
                "fixture_hash": fixture.fixture_hash,
                "fixture_frames": len(fixture.images),
                "frame_size": [FRAME_WIDTH, FRAME_HEIGHT],
                "workload": "cv2.cvtColor BGR2RGB and 5x5 GaussianBlur per frame",
                "warmup_seconds": args.warmup_seconds,
                "block_seconds": args.block_seconds,
                "blocks_per_condition": BLOCKS,
                "order": "alternating, starting condition flips each pair",
            },
            "enabled_blocks": enabled,
            "disabled_blocks": disabled,
            "deltas": {
                "pooled_per_frame": {
                    "median_ms": median_delta_ms,
                    "p95_ms": p95_delta_ms,
                    "samples": len(pooled),
                },
                "block_level": {
                    "p50": {
                        "values_ms": p50_deltas,
                        "median_ms": statistics.median(p50_deltas),
                        "mean_ci95_ms": mean_ci95(p50_deltas),
                    },
                    "p95": {
                        "values_ms": p95_deltas,
                        "median_ms": statistics.median(p95_deltas),
                        "mean_ci95_ms": mean_ci95(p95_deltas),
                    },
                },
            },
            "target_ms": TARGET_MS,
            "target_passed": median_delta_ms <= TARGET_MS
            and p95_delta_ms <= TARGET_MS,
        }
        output = json.dumps(report, indent=2)
        if args.json:
            destination = Path(args.json)
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(output, encoding="utf-8")
        print(output)


if __name__ == "__main__":
    main()
