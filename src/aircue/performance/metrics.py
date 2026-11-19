"""Rolling latency metrics, target comparison, and JSON reports (design.md D7)."""

from __future__ import annotations

import json
import math
import time
from collections import deque
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import StrEnum

from aircue.config.schema import TierConfig
from aircue.performance.timing import FrameTimings, Stage

WINDOW_SAMPLES = 4096


def percentile_ns(samples: tuple[int, ...] | list[int], percent: float) -> int:
    """Nearest-rank percentile, so known samples have exact expected results."""
    if not samples:
        raise ValueError("percentile needs at least one sample")
    ordered = sorted(samples)
    rank = max(1, math.ceil(percent / 100 * len(ordered)))
    return ordered[rank - 1]


class RollingMetric:
    """Bounded sample ring that also evicts anything older than its window."""

    def __init__(
        self, window_ns: int, *, max_samples: int = WINDOW_SAMPLES
    ) -> None:
        self._window_ns = window_ns
        self._samples: deque[tuple[int, int]] = deque(maxlen=max_samples)

    def add(self, timestamp_ns: int, value_ns: int) -> None:
        self._samples.append((timestamp_ns, value_ns))
        self._evict(timestamp_ns)

    def values(self, now_ns: int) -> tuple[int, ...]:
        self._evict(now_ns)
        return tuple(value for _, value in self._samples)

    def _evict(self, now_ns: int) -> None:
        cutoff = now_ns - self._window_ns
        while self._samples and self._samples[0][0] < cutoff:
            self._samples.popleft()


class MetricsRecorder:
    """Records named latency samples over the operational window."""

    def __init__(
        self,
        *,
        window_s: float = 10.0,
        clock_ns: Callable[[], int] = time.monotonic_ns,
        max_samples: int = WINDOW_SAMPLES,
    ) -> None:
        self._window_ns = int(window_s * 1_000_000_000)
        self._clock_ns = clock_ns
        self._max_samples = max_samples
        self._metrics: dict[str, RollingMetric] = {}
        self._frames: deque[int] = deque(maxlen=max_samples)

    def record(
        self, name: str, value_ns: int, *, timestamp_ns: int | None = None
    ) -> None:
        now = self._clock_ns() if timestamp_ns is None else timestamp_ns
        self._metric(name).add(now, value_ns)

    def record_frame(self, *, timestamp_ns: int | None = None) -> None:
        now = self._clock_ns() if timestamp_ns is None else timestamp_ns
        self._frames.append(now)

    def record_timings(
        self, timings: FrameTimings, *, timestamp_ns: int | None = None
    ) -> None:
        now = self._clock_ns() if timestamp_ns is None else timestamp_ns
        for span in timings.spans:
            self.record(span.stage.value, span.duration_ns, timestamp_ns=now)
        compute_ns = recognition_compute_ns(timings)
        if compute_ns is not None:
            self.record("recognition_compute", compute_ns, timestamp_ns=now)

    def values(self, name: str, *, now_ns: int | None = None) -> tuple[int, ...]:
        metric = self._metrics.get(name)
        if metric is None:
            return ()
        now = self._clock_ns() if now_ns is None else now_ns
        return metric.values(now)

    def names(self) -> tuple[str, ...]:
        return tuple(self._metrics)

    def frame_rate_fps(self, *, now_ns: int | None = None) -> float | None:
        now = self._clock_ns() if now_ns is None else now_ns
        cutoff = now - self._window_ns
        while self._frames and self._frames[0] < cutoff:
            self._frames.popleft()
        if len(self._frames) < 2:
            return None
        span_ns = self._frames[-1] - self._frames[0]
        if span_ns <= 0:
            return None
        return (len(self._frames) - 1) * 1_000_000_000 / span_ns

    def _metric(self, name: str) -> RollingMetric:
        metric = self._metrics.get(name)
        if metric is None:
            metric = RollingMetric(self._window_ns, max_samples=self._max_samples)
            self._metrics[name] = metric
        return metric


def recognition_compute_ns(timings: FrameTimings) -> int | None:
    """Preprocessed frame available to classification complete, on the perf clock."""
    spans = {span.stage: span for span in timings.spans if span.clock == "perf"}
    preprocessing = spans.get(Stage.PREPROCESSING)
    classification = spans.get(Stage.CLASSIFICATION)
    if preprocessing is None or classification is None:
        return None
    return max(0, classification.end_ns - preprocessing.end_ns)


@dataclass(frozen=True)
class MetricTarget:
    p50_ms: float | None = None
    p95_ms: float | None = None
    intentional_delay_ms: float = 0.0


@dataclass(frozen=True)
class PerformanceTargets:
    basis: str
    base_p50_ms: float
    base_p95_ms: float
    recognition_compute_p95_ms: float

    @classmethod
    def from_tier(cls, tier: TierConfig, *, basis: str) -> PerformanceTargets:
        return cls(
            basis=basis,
            base_p50_ms=tier.base_latency_p50_ms,
            base_p95_ms=tier.base_latency_p95_ms,
            recognition_compute_p95_ms=tier.recognition_compute_p95_ms,
        )

    def metric_targets(
        self, extra: Mapping[str, MetricTarget] | None = None
    ) -> dict[str, MetricTarget]:
        """Base targets for no-delay actions, and the per-frame compute budget."""
        targets = {
            "pointer": MetricTarget(self.base_p50_ms, self.base_p95_ms),
            "scroll": MetricTarget(self.base_p50_ms, self.base_p95_ms),
            "recognition_compute": MetricTarget(
                p95_ms=self.recognition_compute_p95_ms
            ),
        }
        targets.update(extra or {})
        return targets


class BenchmarkMode(StrEnum):
    REPLAY = "REPLAY"
    LIVE_CAMERA = "LIVE_CAMERA"


class AdapterMode(StrEnum):
    REAL = "REAL"
    NOOP = "NOOP"


@dataclass(frozen=True)
class MetricResult:
    name: str
    p50_ns: int
    p95_ns: int
    samples: int
    target: MetricTarget | None = None
    passed: bool | None = None
    live_only: bool = False


@dataclass(frozen=True)
class PerformanceReport:
    benchmark_mode: BenchmarkMode
    adapter_mode: AdapterMode
    target_basis: str
    metrics: tuple[MetricResult, ...]
    slowest_stage: str | None = None
    frame_rate_fps: float | None = None
    fixture_hash: str | None = None
    simulated_clock: bool | None = None

    @property
    def passed(self) -> bool | None:
        judged = [metric.passed for metric in self.metrics if metric.passed is not None]
        if not judged:
            return None
        return all(judged)

    @property
    def sample_count(self) -> int:
        return sum(metric.samples for metric in self.metrics)

    def as_dict(self) -> dict[str, object]:
        return {
            "benchmark_mode": self.benchmark_mode.value,
            "adapter_mode": self.adapter_mode.value,
            "target_basis": self.target_basis,
            "frame_rate_fps": self.frame_rate_fps,
            "slowest_stage": self.slowest_stage,
            "fixture_hash": self.fixture_hash,
            "simulated_clock": self.simulated_clock,
            "sample_count": self.sample_count,
            "passed": self.passed,
            "metrics": {
                metric.name: {
                    "p50_ms": round(metric.p50_ns / 1_000_000, 3),
                    "p95_ms": round(metric.p95_ns / 1_000_000, 3),
                    "samples": metric.samples,
                    "intentional_delay_ms": (
                        0.0 if metric.target is None else metric.target.intentional_delay_ms
                    ),
                    "target_p50_ms": (
                        None if metric.target is None else metric.target.p50_ms
                    ),
                    "target_p95_ms": (
                        None if metric.target is None else metric.target.p95_ms
                    ),
                    "live_only": metric.live_only,
                    "passed": metric.passed,
                }
                for metric in self.metrics
            },
        }

    def to_json(self) -> str:
        return json.dumps(self.as_dict(), indent=2, sort_keys=True)


_STAGE_NAMES = {stage.value for stage in Stage}
_LIVE_ONLY_SUFFIXES = (".gesture_response", ".capture_to_action")
_LIVE_ONLY_NAMES = {"gesture_response", "capture_to_action"}


def is_live_only_metric(name: str) -> bool:
    """True for metrics replay must not use as live-camera evidence."""
    return name in _LIVE_ONLY_NAMES or name.endswith(_LIVE_ONLY_SUFFIXES)


def build_report(
    recorder: MetricsRecorder,
    targets: PerformanceTargets,
    *,
    benchmark_mode: BenchmarkMode,
    adapter_mode: AdapterMode,
    metric_targets: Mapping[str, MetricTarget] | None = None,
    fixture_hash: str | None = None,
    simulated_clock: bool | None = None,
    now_ns: int | None = None,
) -> PerformanceReport:
    """Percentile snapshot over the rolling window, with pass/fail per target."""
    declared = targets.metric_targets(metric_targets)
    results: list[MetricResult] = []
    for name in recorder.names():
        values = recorder.values(name, now_ns=now_ns)
        if not values:
            continue
        target = declared.get(name)
        live_only = is_live_only_metric(name)
        results.append(
            MetricResult(
                name=name,
                p50_ns=percentile_ns(values, 50),
                p95_ns=percentile_ns(values, 95),
                samples=len(values),
                target=target,
                passed=(
                    None
                    if benchmark_mode is BenchmarkMode.REPLAY and live_only
                    else _passed(values, target)
                ),
                live_only=live_only,
            )
        )

    stages = [metric for metric in results if metric.name in _STAGE_NAMES]
    slowest = max(stages, key=lambda metric: metric.p95_ns).name if stages else None
    return PerformanceReport(
        benchmark_mode=benchmark_mode,
        adapter_mode=adapter_mode,
        target_basis=targets.basis,
        metrics=tuple(results),
        slowest_stage=slowest,
        frame_rate_fps=recorder.frame_rate_fps(now_ns=now_ns),
        fixture_hash=fixture_hash,
        simulated_clock=simulated_clock,
    )


def _passed(values: tuple[int, ...], target: MetricTarget | None) -> bool | None:
    if target is None:
        return None
    passed = True
    if target.p50_ms is not None:
        passed = passed and _ms(values, 50) <= target.p50_ms
    if target.p95_ms is not None:
        passed = passed and _ms(values, 95) <= target.p95_ms
    return passed


def _ms(values: tuple[int, ...], percent: float) -> float:
    return percentile_ns(values, percent) / 1_000_000


class BenchmarkPhase(StrEnum):
    WARMUP = "warmup"
    MEASURING = "measuring"
    COMPLETE = "complete"


@dataclass(frozen=True)
class BenchmarkWindow:
    """A 10-second warm-up followed by 60 seconds of measurement by default."""

    started_ns: int
    warmup_s: float = 10.0
    measure_s: float = 60.0

    def phase(self, now_ns: int) -> BenchmarkPhase:
        elapsed_ns = now_ns - self.started_ns
        if elapsed_ns < self.warmup_s * 1_000_000_000:
            return BenchmarkPhase.WARMUP
        if elapsed_ns < (self.warmup_s + self.measure_s) * 1_000_000_000:
            return BenchmarkPhase.MEASURING
        return BenchmarkPhase.COMPLETE

    def accepts(self, now_ns: int) -> bool:
        return self.phase(now_ns) is BenchmarkPhase.MEASURING
