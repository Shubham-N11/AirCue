from __future__ import annotations

from aircue.performance.frequency import AdaptiveFrequencyController


def controller(**overrides) -> AdaptiveFrequencyController:
    settings = {
        "min_fps": 15.0,
        "max_fps": 60.0,
        "start_fps": 60.0,
        "target_ms": 35.0,
        "step_fps": 5.0,
        "window_ms": 1_000,
        "recovery_ms": 2_000,
        "cooldown_ms": 500,
        "min_samples": 3,
        "queue_threshold": 2,
        "cpu_ceiling": 0.85,
    }
    settings.update(overrides)
    return AdaptiveFrequencyController(**settings)


def feed(
    subject: AdaptiveFrequencyController,
    *,
    compute_ms: float,
    times_ms: tuple[int, ...],
    queue_depth: int = 0,
    cpu_fraction: float | None = 0.10,
):
    decision = None
    for now_ms in times_ms:
        decision = subject.observe(
            compute_ms=compute_ms,
            queue_depth=queue_depth,
            cpu_fraction=cpu_fraction,
            now_ns=now_ms * 1_000_000,
        )
    return decision


def test_stable_latency_keeps_the_profile_maximum() -> None:
    subject = controller()

    decision = feed(subject, compute_ms=10.0, times_ms=(0, 100, 200))

    assert decision is not None
    assert decision.changed is False
    assert subject.fps == 60.0


def test_sustained_latency_overload_reduces_one_step() -> None:
    subject = controller()

    decision = feed(subject, compute_ms=40.0, times_ms=(0, 100, 200))

    assert decision is not None
    assert decision.changed is True
    assert subject.fps == 55.0
    assert "latency" in decision.reason


def test_fewer_samples_than_the_minimum_do_not_change_frequency() -> None:
    subject = controller()

    decision = feed(subject, compute_ms=90.0, times_ms=(0, 100))

    assert decision is not None
    assert decision.changed is False
    assert subject.fps == 60.0


def test_a_single_slow_frame_does_not_count_as_overload() -> None:
    subject = controller()

    feed(subject, compute_ms=10.0, times_ms=(0, 100))
    decision = feed(subject, compute_ms=90.0, times_ms=(200,))

    assert decision is not None
    assert decision.changed is False
    assert subject.fps == 60.0


def test_queue_backlog_reduces_frequency() -> None:
    subject = controller()

    decision = feed(
        subject, compute_ms=10.0, times_ms=(0, 100, 200), queue_depth=2
    )

    assert decision is not None
    assert decision.changed is True
    assert subject.fps == 55.0
    assert "queue depth" in decision.reason


def test_cpu_pressure_reduces_frequency() -> None:
    subject = controller()

    decision = feed(
        subject,
        compute_ms=10.0,
        times_ms=(0, 100, 200),
        cpu_fraction=0.90,
    )

    assert decision is not None
    assert decision.changed is True
    assert subject.fps == 55.0
    assert "cpu" in decision.reason


def test_frequency_never_falls_below_the_profile_minimum() -> None:
    subject = controller(start_fps=15.0)

    decision = feed(subject, compute_ms=90.0, times_ms=(0, 100, 200))

    assert decision is not None
    assert decision.changed is False
    assert subject.fps == 15.0


def test_cooldown_blocks_a_second_reduction() -> None:
    subject = controller()
    feed(subject, compute_ms=40.0, times_ms=(0, 100, 200))
    assert subject.fps == 55.0

    decision = feed(subject, compute_ms=40.0, times_ms=(300, 400, 500))

    assert decision is not None
    assert decision.changed is False
    assert subject.fps == 55.0

    decision = feed(subject, compute_ms=40.0, times_ms=(800, 900, 1_000))

    assert decision is not None
    assert decision.changed is False
    assert subject.fps == 50.0


def test_recovery_is_gradual_and_needs_the_full_window() -> None:
    subject = controller()
    feed(subject, compute_ms=40.0, times_ms=(0, 100, 200))
    assert subject.fps == 55.0

    earlier = feed(
        subject,
        compute_ms=10.0,
        times_ms=tuple(range(1_000, 2_801, 200)),
    )

    assert earlier is not None
    assert earlier.changed is False
    assert subject.fps == 55.0

    decision = feed(subject, compute_ms=10.0, times_ms=(3_400,))

    assert decision is not None
    assert decision.changed is True
    assert subject.fps == 60.0
    assert "recovered" in decision.reason


def test_recovery_stops_and_overload_wins_again() -> None:
    subject = controller(cooldown_ms=0)
    feed(subject, compute_ms=40.0, times_ms=(0, 100, 200))
    assert subject.fps == 55.0

    feed(subject, compute_ms=10.0, times_ms=(1_000, 1_200, 1_400))
    assert subject.fps == 55.0

    decision = feed(subject, compute_ms=90.0, times_ms=(2_400, 2_600, 2_800))

    assert decision is not None
    assert decision.changed is True
    assert subject.fps == 50.0


def test_forced_frequency_ignores_observations() -> None:
    subject = controller(start_fps=24.0, forced=True)

    decision = feed(subject, compute_ms=200.0, times_ms=(0, 100, 200))

    assert decision is not None
    assert decision.changed is False
    assert decision.reason == "frequency is forced"
    assert subject.fps == 24.0


def test_start_frequency_is_clamped_to_the_profile_bounds() -> None:
    assert controller(start_fps=100.0).fps == 60.0
    assert controller(start_fps=5.0).fps == 15.0


def test_repeated_changes_stay_within_profile_bounds() -> None:
    subject = controller(cooldown_ms=0)
    now_ms = 0

    while subject.fps > 15.0:
        decision = feed(
            subject, compute_ms=90.0, times_ms=(now_ms, now_ms + 100, now_ms + 200)
        )
        now_ms += 300
        assert decision is not None
        assert 15.0 <= decision.fps <= 60.0

    decision = feed(subject, compute_ms=90.0, times_ms=(now_ms, now_ms + 100))
    assert decision is not None
    assert decision.fps == 15.0

    now_ms += 10_000
    while subject.fps < 60.0:
        decision = feed(
            subject, compute_ms=10.0, times_ms=(now_ms, now_ms + 100, now_ms + 200)
        )
        now_ms += 300
        assert decision is not None
        assert 15.0 <= decision.fps <= 60.0

    decision = feed(subject, compute_ms=10.0, times_ms=(now_ms, now_ms + 100))
    assert decision is not None
    assert decision.fps == 60.0
