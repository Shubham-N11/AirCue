"""Per-stage timing spans carried with one frame (design.md D7)."""

from __future__ import annotations

import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from enum import StrEnum


class Stage(StrEnum):
    CAPTURE = "capture"
    QUEUE_WAIT = "queue_wait"
    PREPROCESSING = "preprocessing"
    INFERENCE = "inference"
    LANDMARK_PROCESSING = "landmark_processing"
    FEATURE_EXTRACTION = "feature_extraction"
    CLASSIFICATION = "classification"
    TEMPORAL_CONFIRMATION = "temporal_confirmation"
    COMMAND_VALIDATION = "command_validation"
    DISPATCH_QUEUE_WAIT = "dispatch_queue_wait"
    ADAPTER_EXECUTION = "adapter_execution"


@dataclass(frozen=True)
class StageSpan:
    stage: Stage
    start_ns: int
    end_ns: int
    # "perf" spans use perf_counter_ns; "frame" spans use frame timestamps.
    clock: str = "perf"

    @property
    def duration_ns(self) -> int:
        return self.end_ns - self.start_ns


@dataclass
class FrameTimings:
    """Mutable stage spans shared by a frame, its gesture, and its command."""

    spans: list[StageSpan] = field(default_factory=list)
    # Frame-clock capture timestamp of the frame that produced the action.
    capture_ts_ns: int | None = None

    def record(
        self,
        stage: Stage,
        start_ns: int,
        end_ns: int,
        *,
        clock: str = "perf",
    ) -> None:
        self.spans.append(StageSpan(stage, start_ns, end_ns, clock))


@contextmanager
def measure(
    timings: FrameTimings | None, stage: Stage
) -> Iterator[None]:
    """Record one stage; a None timings object means instrumentation is off."""
    if timings is None:
        yield
        return
    started_ns = time.perf_counter_ns()
    try:
        yield
    finally:
        timings.record(stage, started_ns, time.perf_counter_ns())
