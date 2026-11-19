"""Rolling metrics: exact percentiles, targets, reports, and benchmark windows."""

from __future__ import annotations

import json

import pytest

from aircue.performance.metrics import (
    AdapterMode,
    BenchmarkMode,
    BenchmarkPhase,
    BenchmarkWindow,
    MetricsRecorder,
    MetricTarget,
    PerformanceTargets,
    build_report,
    percentile_ns,
    recognition_compute_ns,
)
from aircue.performance.timing import FrameTimings, Stage

MS = 1_000_000
SECOND = 1_000_000_000


def test_percentiles_are_exact_nearest_rank() -> None:
    values = list(range(1, 101))
    assert percentile_ns(values, 50) == 50
    assert percentile_ns(values, 95) == 95
    assert percentile_ns([3], 95) == 3
    assert percentile_ns([1, 2, 3, 4], 50) == 2
    assert percentile_ns([1, 2, 3, 4], 95) == 4
    with pytest.raises(ValueError):
        percentile_ns([], 50)


def test_the_rolling_window_evicts_samples_older_than_ten_seconds() -> None:
    recorder = MetricsRecorder(window_s=10.0, clock_ns=lambda: 0)
    recorder.record("pointer", 1 * MS, timestamp_ns=0)
    recorder.record("pointer", 2 * MS, timestamp_ns=20_000 * MS)

    assert recorder.values("pointer", now_ns=20_000 * MS) == (2 * MS,)


def test_the_sample_ring_is_bounded() -> None:
    recorder = MetricsRecorder(window_s=100.0, clock_ns=lambda: 0, max_samples=3)
    for value in range(1, 6):
        recorder.record("pointer", value * MS)

    assert recorder.values("pointer") == (3 * MS, 4 * MS, 5 * MS)


def test_recognition_compute_excludes_temporal_confirmation() -> None:
    timings = FrameTimings()
    timings.record(Stage.PREPROCESSING, 0, 10 * MS)
    timings.record(Stage.CLASSIFICATION, 10 * MS, 25 * MS)
    timings.record(Stage.TEMPORAL_CONFIRMATION, 0, 500 * MS, clock="frame")

    assert recognition_compute_ns(timings) == 15 * MS


def test_a_report_marks_targets_and_identifies_the_slowest_stage() -> None:
    recorder = MetricsRecorder(window_s=10.0, clock_ns=lambda: 0)
    timings = FrameTimings()
    timings.record(Stage.PREPROCESSING, 0, 5 * MS)
    timings.record(Stage.INFERENCE, 5 * MS, 45 * MS)
    timings.record(Stage.CLASSIFICATION, 45 * MS, 50 * MS)
    recorder.record_timings(timings, timestamp_ns=0)
    recorder.record("pointer", 80 * MS)
    recorder.record("pointer", 120 * MS)

    report = build_report(
        recorder,
        PerformanceTargets("baseline", 100.0, 150.0, 50.0),
        benchmark_mode=BenchmarkMode.REPLAY,
        adapter_mode=AdapterMode.NOOP,
        now_ns=0,
    )

    assert report.slowest_stage == "inference"
    assert report.passed is True
    by_name = {metric.name: metric for metric in report.metrics}
    assert by_name["pointer"].p50_ns == 80 * MS
    assert by_name["pointer"].p95_ns == 120 * MS
    assert by_name["pointer"].samples == 2
    assert by_name["recognition_compute"].p95_ns == 45 * MS


def test_a_missed_target_fails_and_high_fps_does_not_rescue_it() -> None:
    recorder = MetricsRecorder(window_s=10.0, clock_ns=lambda: 0)
    timings = FrameTimings()
    timings.record(Stage.PREPROCESSING, 0, 5 * MS)
    timings.record(Stage.CLASSIFICATION, 5 * MS, 60 * MS)
    recorder.record_timings(timings, timestamp_ns=0)
    recorder.record("pointer", 200 * MS)
    for index in range(31):
        recorder.record_frame(timestamp_ns=index * 33 * MS)

    report = build_report(
        recorder,
        PerformanceTargets("baseline", 100.0, 150.0, 50.0),
        benchmark_mode=BenchmarkMode.LIVE_CAMERA,
        adapter_mode=AdapterMode.REAL,
        now_ns=30 * 33 * MS,
    )

    assert report.frame_rate_fps == pytest.approx(1000 / 33, rel=0.01)
    assert report.passed is False
    by_name = {metric.name: metric for metric in report.metrics}
    assert by_name["recognition_compute"].passed is False
    assert by_name["pointer"].passed is False


def test_the_json_report_carries_metadata_and_intentional_delay_only() -> None:
    recorder = MetricsRecorder(window_s=10.0, clock_ns=lambda: 0)
    recorder.record("fist_pause", 250 * MS, timestamp_ns=0)
    recorder.record_frame(timestamp_ns=0)
    recorder.record_frame(timestamp_ns=20 * MS)

    report = build_report(
        recorder,
        PerformanceTargets("tier2", 70.0, 100.0, 35.0),
        benchmark_mode=BenchmarkMode.REPLAY,
        adapter_mode=AdapterMode.NOOP,
        metric_targets={
            "fist_pause": MetricTarget(
                p50_ms=300.0, p95_ms=350.0, intentional_delay_ms=200.0
            )
        },
        now_ns=20 * MS,
    )

    payload = json.loads(report.to_json())
    assert payload["benchmark_mode"] == "REPLAY"
    assert payload["adapter_mode"] == "NOOP"
    assert payload["target_basis"] == "tier2"
    assert payload["sample_count"] == 1
    assert payload["passed"] is True
    metric = payload["metrics"]["fist_pause"]
    assert metric["p50_ms"] == 250.0
    assert metric["p95_ms"] == 250.0
    assert metric["samples"] == 1
    assert metric["intentional_delay_ms"] == 200.0
    assert metric["passed"] is True
    assert "image" not in report.to_json()


def test_a_replay_report_never_passes_live_only_metrics() -> None:
    recorder = MetricsRecorder(window_s=10.0, clock_ns=lambda: 0)
    recorder.record("click.gesture_response", 50 * MS, timestamp_ns=0)
    recorder.record("click.capture_to_action", 60 * MS, timestamp_ns=0)
    recorder.record("pointer", 40 * MS, timestamp_ns=0)
    targets = PerformanceTargets("tier2", 100.0, 150.0, 50.0)
    extras = {"click.gesture_response": MetricTarget(100.0, 150.0)}

    replay = build_report(
        recorder,
        targets,
        benchmark_mode=BenchmarkMode.REPLAY,
        adapter_mode=AdapterMode.NOOP,
        metric_targets=extras,
        fixture_hash="fixture-sha",
        simulated_clock=True,
        now_ns=0,
    )

    by_name = {metric.name: metric for metric in replay.metrics}
    assert by_name["click.gesture_response"].live_only is True
    assert by_name["click.gesture_response"].passed is None
    assert by_name["click.capture_to_action"].live_only is True
    assert by_name["click.capture_to_action"].passed is None
    assert by_name["pointer"].live_only is False
    assert by_name["pointer"].passed is True
    assert replay.passed is True

    payload = json.loads(replay.to_json())
    assert payload["fixture_hash"] == "fixture-sha"
    assert payload["simulated_clock"] is True
    assert payload["metrics"]["click.gesture_response"]["live_only"] is True
    assert payload["metrics"]["click.gesture_response"]["passed"] is None

    live = build_report(
        recorder,
        targets,
        benchmark_mode=BenchmarkMode.LIVE_CAMERA,
        adapter_mode=AdapterMode.NOOP,
        metric_targets=extras,
        now_ns=0,
    )
    live_by_name = {metric.name: metric for metric in live.metrics}
    assert live_by_name["click.gesture_response"].passed is True


def test_an_empty_report_is_not_marked_as_passed() -> None:
    report = build_report(
        MetricsRecorder(clock_ns=lambda: 0),
        PerformanceTargets("baseline", 100.0, 150.0, 50.0),
        benchmark_mode=BenchmarkMode.REPLAY,
        adapter_mode=AdapterMode.NOOP,
        now_ns=0,
    )

    assert report.passed is None
    assert report.sample_count == 0


def test_the_benchmark_window_warms_up_then_measures_for_sixty_seconds() -> None:
    window = BenchmarkWindow(started_ns=0)

    assert window.phase(10 * SECOND - 1) is BenchmarkPhase.WARMUP
    assert window.phase(10 * SECOND) is BenchmarkPhase.MEASURING
    assert window.phase(70 * SECOND - 1) is BenchmarkPhase.MEASURING
    assert window.phase(70 * SECOND) is BenchmarkPhase.COMPLETE
    assert window.accepts(10 * SECOND) is True
    assert window.accepts(9 * SECOND) is False
    assert window.accepts(70 * SECOND) is False
