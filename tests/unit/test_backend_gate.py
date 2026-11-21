from __future__ import annotations

import math

import pytest

from aircue.hardware import (
    BackendCandidate,
    benchmark_candidates,
    measure_backend,
    select_backend,
)


def latencies(center: float, spread: float, count: int = 20) -> list[float]:
    return [
        center - spread + 2 * spread * index / (count - 1)
        for index in range(count)
    ]


def test_a_gpu_at_least_ten_percent_faster_is_selected() -> None:
    decision = select_backend(
        [
            measure_backend("cpu", [100.0] * 20),
            measure_backend("gpu", [50.0] * 20),
        ]
    )

    assert decision.selected == "gpu"
    assert decision.margin_percent == pytest.approx(50.0)
    assert "passed" in decision.reason


def test_a_slower_gpu_stays_unused() -> None:
    decision = select_backend(
        [
            measure_backend("cpu", latencies(100, 2)),
            measure_backend("gpu", latencies(150, 2)),
        ]
    )

    assert decision.selected == "cpu"
    assert decision.margin_percent is None
    assert "median improvement under 10%" in decision.reason


def test_close_results_keep_the_cpu() -> None:
    decision = select_backend(
        [
            measure_backend("cpu", latencies(100, 2)),
            measure_backend("gpu", latencies(95, 2)),
        ]
    )

    assert decision.selected == "cpu"
    assert "gpu rejected" in decision.reason


def test_overlapping_confidence_intervals_keep_the_cpu() -> None:
    decision = select_backend(
        [
            measure_backend("cpu", [100.0] * 10 + [130.0] * 10),
            measure_backend("gpu", [70.0] * 10 + [120.0] * 10),
        ]
    )

    assert decision.selected == "cpu"
    assert "confidence intervals overlap" in decision.reason


def test_a_worse_p95_keeps_the_cpu() -> None:
    decision = select_backend(
        [
            measure_backend("cpu", latencies(100, 2)),
            measure_backend("gpu", [80.0] * 18 + [110.0] * 2),
        ]
    )

    assert decision.selected == "cpu"
    assert "p95 worse" in decision.reason


def test_a_worse_failure_rate_keeps_the_cpu() -> None:
    decision = select_backend(
        [
            measure_backend("cpu", latencies(100, 2)),
            measure_backend("gpu", latencies(50, 2), failures=2),
        ]
    )

    assert decision.selected == "cpu"
    assert "failure rate worse" in decision.reason


def test_no_alternative_backend_selects_the_cpu() -> None:
    decision = select_backend([measure_backend("cpu", latencies(100, 2))])

    assert decision.selected == "cpu"
    assert decision.margin_percent is None
    assert "no alternative" in decision.reason


def test_an_invalid_cpu_falls_back_to_the_cpu_name() -> None:
    decision = select_backend(
        [
            measure_backend("cpu", []),
            measure_backend("gpu", latencies(50, 2)),
        ]
    )

    assert decision.selected == "cpu"
    assert decision.reason == "cpu measurement unavailable"


@pytest.mark.parametrize(
    "values",
    [
        [],
        [10.0, math.nan],
        [10.0, -1.0],
        [math.inf],
    ],
)
def test_malformed_latency_evidence_is_invalid(values: list[float]) -> None:
    measurement = measure_backend("gpu", values)

    assert measurement.valid is False
    assert measurement.median_ms is None
    assert measurement.reason


def test_a_negative_failure_count_is_invalid() -> None:
    assert measure_backend("gpu", [10.0], failures=-1).valid is False


def test_failure_rate_uses_attempts_and_successful_samples() -> None:
    measurement = measure_backend("gpu", [10.0, 20.0], failures=2)

    assert measurement.samples == 2
    assert measurement.failures == 2
    assert measurement.failure_rate == 0.5


def test_known_samples_produce_exact_percentiles() -> None:
    measurement = measure_backend("cpu", [5.0, 1.0, 3.0, 2.0, 4.0])

    assert measurement.median_ms == 3.0
    assert measurement.p95_ms == 5.0
    assert measurement.median_ci_ms == (1.0, 5.0)


class FakeClock:
    def __init__(self, step_ns: int) -> None:
        self.now_ns = 0
        self.step_ns = step_ns

    def __call__(self) -> int:
        return self.now_ns


class FakeProbe:
    def __init__(self, clock: FakeClock, *, fail_after: int | None = None) -> None:
        self.clock = clock
        self.fail_after = fail_after
        self.calls = 0
        self.closed = False

    def infer(self) -> None:
        if self.fail_after is not None and self.calls >= self.fail_after:
            raise RuntimeError("inference failed")
        self.calls += 1
        self.clock.now_ns += self.clock.step_ns

    def close(self) -> None:
        self.closed = True


def test_warmup_runs_before_measurement_and_closes_the_probe() -> None:
    clock = FakeClock(5_000_000)
    probe = FakeProbe(clock)
    measurement = benchmark_candidates(
        [BackendCandidate("cpu", lambda: probe)],
        warmup=3,
        samples=4,
        clock_ns=clock,
    )[0]

    assert probe.calls == 7
    assert probe.closed is True
    assert measurement.median_ms == 5.0
    assert measurement.samples == 4


def test_an_initialization_failure_is_excluded() -> None:
    def unavailable() -> FakeProbe:
        raise OSError("no GPU runtime")

    measurements = benchmark_candidates(
        [BackendCandidate("gpu", unavailable)], warmup=0, samples=1
    )

    assert measurements[0].valid is False
    assert "initialization failed" in measurements[0].reason


def test_a_warmup_failure_is_excluded() -> None:
    clock = FakeClock(1_000_000)
    measurements = benchmark_candidates(
        [BackendCandidate("gpu", lambda: FakeProbe(clock, fail_after=0))],
        warmup=1,
        samples=2,
    )

    assert measurements[0].valid is False
    assert "warm-up failed" in measurements[0].reason


def test_inference_failures_are_counted_in_the_rate() -> None:
    clock = FakeClock(1_000_000)
    measurements = benchmark_candidates(
        [BackendCandidate("gpu", lambda: FakeProbe(clock, fail_after=2))],
        warmup=0,
        samples=4,
    )

    assert measurements[0].samples == 2
    assert measurements[0].failures == 2
    assert measurements[0].failure_rate == 0.5


def test_a_zero_sample_benchmark_is_rejected() -> None:
    with pytest.raises(ValueError, match="samples"):
        benchmark_candidates(
            [BackendCandidate("cpu", lambda: FakeProbe(FakeClock(1)))],
            samples=0,
        )
