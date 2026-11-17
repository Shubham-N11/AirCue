from __future__ import annotations

import math

import pytest

from aircue.commands.pointer import PointerSmoother

MS = 1_000_000
FRAME_NS = 33 * MS


def sample(
    smoother: PointerSmoother, point: tuple[float, float], frame: int
) -> tuple[float, float] | None:
    return smoother.update(point, frame * FRAME_NS)


def test_the_first_valid_sample_initializes_the_position() -> None:
    smoother = PointerSmoother()
    assert sample(smoother, (0.4, 0.6), 0) == (0.4, 0.6)
    assert smoother.position == (0.4, 0.6)


def test_stationary_jitter_inside_the_dead_zone_never_moves_the_output() -> None:
    smoother = PointerSmoother(dead_zone=0.01)
    sample(smoother, (0.5, 0.5), 0)

    offsets = [0.004, -0.003, 0.002, -0.004, 0.001, 0.003, -0.002]
    for frame in range(1, 71):
        offset = offsets[frame % len(offsets)]
        output = sample(smoother, (0.5 + offset, 0.5 - offset), frame)
        assert output == (0.5, 0.5)


def test_a_fast_sweep_tracks_the_hand_with_a_small_lag() -> None:
    smoother = PointerSmoother(min_alpha=0.20, max_alpha=0.45)
    sample(smoother, (0.5, 0.5), 0)

    output = (0.5, 0.5)
    for frame in range(1, 11):
        raw = (0.5 + 0.04 * frame, 0.5)
        output = sample(smoother, raw, frame)
        assert output is not None
    assert 0.5 + 0.4 - output[0] < 0.08


def test_a_stationary_target_still_converges_inside_the_dead_zone() -> None:
    smoother = PointerSmoother(dead_zone=0.01, min_alpha=0.20, max_alpha=0.45)
    sample(smoother, (0.5, 0.5), 0)
    sample(smoother, (0.9, 0.5), 1)

    output = None
    for frame in range(2, 22):
        output = sample(smoother, (0.9, 0.5), frame)
    assert output is not None
    assert abs(output[0] - 0.9) < 0.01


def test_slow_movement_is_smoothed_more_than_fast_movement() -> None:
    smoother = PointerSmoother(min_alpha=0.20, max_alpha=0.45)
    sample(smoother, (0.5, 0.5), 0)

    slow = sample(smoother, (0.512, 0.5), 1)
    fast = sample(smoother, (0.9, 0.5), 1)

    assert slow is not None and fast is not None
    assert slow[0] - 0.5 == pytest.approx(0.26 * 0.012, abs=0.002)
    assert (fast[0] - 0.5) > 10 * (slow[0] - 0.5)


def test_a_slow_drift_accumulates_until_it_crosses_the_dead_zone() -> None:
    smoother = PointerSmoother(dead_zone=0.01)
    sample(smoother, (0.5, 0.5), 0)

    assert sample(smoother, (0.506, 0.5), 1) == (0.5, 0.5)
    assert sample(smoother, (0.512, 0.5), 2) != (0.5, 0.5)


def test_invalidation_freezes_the_last_position() -> None:
    smoother = PointerSmoother()
    sample(smoother, (0.25, 0.75), 0)

    assert sample(smoother, None, 1) is None
    assert smoother.position == (0.25, 0.75)
    assert smoother.update(None, 2 * FRAME_NS) is None
    assert smoother.position == (0.25, 0.75)


def test_reacquisition_resumes_from_the_frozen_position_without_teleporting() -> None:
    smoother = PointerSmoother(dead_zone=0.01)
    sample(smoother, (0.6, 0.4), 0)
    frozen = smoother.position
    assert frozen is not None

    assert sample(smoother, None, 1) is None
    resumed = sample(smoother, (0.9, 0.8), 2)
    assert resumed == frozen

    after = sample(smoother, (0.91, 0.8), 3)
    assert after is not None
    assert math.dist(after, frozen) < 0.01
    assert math.dist(after, (0.91, 0.8)) > 0.25


def test_slow_frames_use_maximum_alpha_to_bound_added_latency() -> None:
    smoother = PointerSmoother(
        min_alpha=0.20, max_alpha=0.45, max_added_latency_ms=40
    )
    smoother.update((0.5, 0.5), 0)

    slow_frame = smoother.update((0.512, 0.5), 50 * MS)
    assert slow_frame is not None
    assert slow_frame[0] - 0.5 == pytest.approx(0.45 * 0.012)


def test_minimum_alpha_cannot_exceed_the_maximum() -> None:
    with pytest.raises(ValueError):
        PointerSmoother(min_alpha=0.5, max_alpha=0.4)
