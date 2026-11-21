"""Backend benchmark gate from design.md D8.

CPU is selected unless another backend is at least 10% lower in median
latency, no worse in p95, no worse in reliability, and has a non-overlapping
median confidence interval. Invalid or failed backends are excluded.
"""

from __future__ import annotations

import math
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Protocol

MIN_MEDIAN_IMPROVEMENT = 0.10
_MEDIAN_Z = 1.96


class BackendProbe(Protocol):
    """Representative inference work for one backend."""

    def infer(self) -> None: ...

    def close(self) -> None: ...


@dataclass(frozen=True)
class BackendCandidate:
    name: str
    create: Callable[[], BackendProbe]


@dataclass(frozen=True)
class BackendMeasurement:
    name: str
    median_ms: float | None
    p95_ms: float | None
    failure_rate: float
    samples: int
    failures: int
    median_ci_ms: tuple[float, float] | None
    valid: bool = True
    reason: str = ""

    @classmethod
    def invalid(cls, name: str, reason: str) -> BackendMeasurement:
        return cls(name, None, None, 0.0, 0, 0, None, False, reason)


@dataclass(frozen=True)
class BackendDecision:
    selected: str
    margin_percent: float | None
    reason: str
    measurements: tuple[BackendMeasurement, ...]


def measure_backend(
    name: str, latencies_ms: Sequence[float], *, failures: int = 0
) -> BackendMeasurement:
    """Summarize one backend; malformed or empty evidence is invalid."""
    values = tuple(float(value) for value in latencies_ms)
    if failures < 0:
        return BackendMeasurement.invalid(name, "failure count is negative")
    if any(not math.isfinite(value) or value < 0 for value in values):
        return BackendMeasurement.invalid(
            name, "latency samples must be finite and non-negative"
        )
    if not values:
        return BackendMeasurement.invalid(name, "no successful samples")
    attempted = len(values) + failures
    return BackendMeasurement(
        name=name,
        median_ms=_percentile(values, 50),
        p95_ms=_percentile(values, 95),
        failure_rate=failures / attempted,
        samples=len(values),
        failures=failures,
        median_ci_ms=_median_ci(values),
    )


def benchmark_candidates(
    candidates: Sequence[BackendCandidate],
    *,
    warmup: int = 5,
    samples: int = 60,
    clock_ns: Callable[[], int] = time.perf_counter_ns,
) -> tuple[BackendMeasurement, ...]:
    """Measure each candidate; init or warm-up failure excludes it."""
    if samples < 1:
        raise ValueError("samples must be at least 1")
    results: list[BackendMeasurement] = []
    for candidate in candidates:
        try:
            probe = candidate.create()
        except Exception as exc:
            results.append(
                BackendMeasurement.invalid(
                    candidate.name, f"initialization failed: {exc}"
                )
            )
            continue
        try:
            results.append(
                _measure_probe(
                    candidate.name,
                    probe,
                    warmup=max(0, warmup),
                    samples=samples,
                    clock_ns=clock_ns,
                )
            )
        finally:
            probe.close()
    return tuple(results)


def select_backend(
    measurements: Sequence[BackendMeasurement],
    *,
    cpu_name: str = "cpu",
) -> BackendDecision:
    """Apply the gate; fail closed to CPU on missing or invalid evidence."""
    evidence = tuple(measurements)
    cpu = next((item for item in evidence if item.name == cpu_name), None)
    if cpu is None or not cpu.valid or cpu.median_ms is None or cpu.p95_ms is None:
        return BackendDecision(cpu_name, None, "cpu measurement unavailable", evidence)

    qualifying: list[BackendMeasurement] = []
    rejected: list[str] = []
    for item in evidence:
        if item.name == cpu_name:
            continue
        if not item.valid:
            rejected.append(f"{item.name} excluded: {item.reason}")
            continue
        assert item.median_ms is not None
        assert item.p95_ms is not None
        median_ok = (
            item.median_ms
            <= cpu.median_ms * (1 - MIN_MEDIAN_IMPROVEMENT)
        )
        p95_ok = item.p95_ms <= cpu.p95_ms
        reliability_ok = item.failure_rate <= cpu.failure_rate
        interval_ok = _median_intervals_disjoint(item, cpu)
        if median_ok and p95_ok and reliability_ok and interval_ok:
            qualifying.append(item)
        else:
            rejected.append(
                _rejection(item, median_ok, p95_ok, reliability_ok, interval_ok)
            )

    if not qualifying:
        reason = "; ".join(rejected) or "no alternative backend was benchmarked"
        return BackendDecision(cpu_name, None, reason, evidence)

    best = min(
        qualifying,
        key=lambda item: item.median_ms if item.median_ms is not None else math.inf,
    )
    assert best.median_ms is not None
    margin = (
        (cpu.median_ms - best.median_ms) / cpu.median_ms * 100
        if cpu.median_ms > 0
        else None
    )
    return BackendDecision(
        best.name,
        margin,
        f"{best.name} passed the 10% median, p95, reliability, and interval gate",
        evidence,
    )


def _measure_probe(
    name: str,
    probe: BackendProbe,
    *,
    warmup: int,
    samples: int,
    clock_ns: Callable[[], int],
) -> BackendMeasurement:
    for _ in range(warmup):
        try:
            probe.infer()
        except Exception as exc:
            return BackendMeasurement.invalid(name, f"warm-up failed: {exc}")
    latencies: list[float] = []
    failures = 0
    for _ in range(samples):
        started_ns = clock_ns()
        try:
            probe.infer()
        except Exception:
            failures += 1
            continue
        latencies.append(max(0, clock_ns() - started_ns) / 1_000_000)
    return measure_backend(name, latencies, failures=failures)


def _percentile(values: Sequence[float], percent: float) -> float:
    ordered = sorted(values)
    rank = max(1, math.ceil(percent / 100 * len(ordered)))
    return ordered[rank - 1]


def _median_ci(values: Sequence[float]) -> tuple[float, float]:
    """Distribution-free median interval from binomial order statistics."""
    ordered = sorted(values)
    count = len(ordered)
    spread = _MEDIAN_Z * math.sqrt(count) / 2
    lower = max(1, math.floor(count / 2 - spread))
    upper = min(count, math.ceil(count / 2 + spread))
    return ordered[lower - 1], ordered[upper - 1]


def _median_intervals_disjoint(
    candidate: BackendMeasurement, cpu: BackendMeasurement
) -> bool:
    if candidate.median_ci_ms is None or cpu.median_ci_ms is None:
        return False
    return candidate.median_ci_ms[1] < cpu.median_ci_ms[0]


def _rejection(
    item: BackendMeasurement,
    median_ok: bool,
    p95_ok: bool,
    reliability_ok: bool,
    interval_ok: bool,
) -> str:
    reasons: list[str] = []
    if not median_ok:
        reasons.append("median improvement under 10%")
    if not p95_ok:
        reasons.append("p95 worse")
    if not reliability_ok:
        reasons.append("failure rate worse")
    if not interval_ok:
        reasons.append("median confidence intervals overlap")
    return f"{item.name} rejected: {', '.join(reasons)}"
