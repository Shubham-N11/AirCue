from __future__ import annotations

import pytest

from aircue.commands.manager import CommandManager
from aircue.commands.scroll import ScrollController, ScrollRejection, ScrollUpdate
from aircue.presentation.target import TargetKind, capabilities_for
from aircue.state.states import InteractionState

S = InteractionState
POINTER = capabilities_for(TargetKind.NORMAL_SLIDESHOW)


def controller(**overrides) -> ScrollController:
    return ScrollController(CommandManager(), **overrides)


def feed(
    subject: ScrollController,
    y: float | None,
    *,
    start_ms: int = 0,
    frames: int = 10,
    step_ms: int = 100,
    state: InteractionState = S.SCROLL_MODE,
    capabilities=POINTER,
    foreground: bool = True,
) -> list[ScrollUpdate]:
    return [
        subject.update(
            y,
            (start_ms + index * step_ms) * 1_000_000,
            state,
            capabilities,
            foreground=foreground,
        )
        for index in range(frames)
    ]


def total_notches(updates: list[ScrollUpdate]) -> int:
    return sum(update.notches for update in updates)


def test_entering_scroll_mode_emits_nothing() -> None:
    subject = controller()
    updates = feed(subject, 0.0, frames=1)
    assert updates[0].notches == 0
    assert updates[0].allowed is True


def test_movement_inside_the_dead_zone_emits_nothing() -> None:
    subject = controller(dead_zone=0.05)
    updates = feed(subject, 0.53, frames=20)
    assert all(update.notches == 0 for update in updates)


def test_hand_up_scrolls_up() -> None:
    subject = controller()
    assert total_notches(feed(subject, 0.3, frames=11)) == 3


def test_hand_down_scrolls_down() -> None:
    subject = controller()
    assert total_notches(feed(subject, 0.7, frames=11)) == -3


def test_invert_reverses_the_direction() -> None:
    subject = controller(invert=True)
    assert total_notches(feed(subject, 0.7, frames=11)) == 3


def test_speed_is_proportional_to_displacement() -> None:
    near = controller()
    far = controller()
    near_total = total_notches(feed(near, 0.4, frames=11))
    far_total = total_notches(feed(far, 0.3, frames=11))
    assert 0 < near_total < far_total


def test_the_rate_never_exceeds_the_maximum() -> None:
    subject = controller(max_notches_per_second=10.0)
    updates = feed(subject, 0.0, frames=101, step_ms=10)
    assert 9 <= total_notches(updates) <= 10


def test_a_long_frame_gap_does_not_burst() -> None:
    subject = controller()
    assert subject.update(0.0, 0, S.SCROLL_MODE, POINTER, foreground=True).notches == 0
    burst = subject.update(5_000 * 1_000_000, 0.0, S.SCROLL_MODE, POINTER, foreground=True)
    assert burst.notches <= 1


def test_returning_to_the_dead_zone_clears_a_partial_notch() -> None:
    subject = controller()
    feed(subject, 0.3, frames=3)
    neutral = subject.update(
        0.5, 300 * 1_000_000, S.SCROLL_MODE, POINTER, foreground=True
    )
    assert neutral.notches == 0

    resumed = feed(subject, 0.3, start_ms=400, frames=2)
    assert all(update.notches == 0 for update in resumed)


def test_reversing_direction_clears_a_partial_notch() -> None:
    subject = controller()
    feed(subject, 0.3, frames=3)
    reversed_frames = feed(subject, 0.7, start_ms=300, frames=2)
    assert all(update.notches == 0 for update in reversed_frames)

    continued = feed(subject, 0.7, start_ms=500, frames=11)
    assert total_notches(continued) < 0


def test_hand_loss_stops_scrolling_immediately_and_reacquires_cleanly() -> None:
    subject = controller()
    feed(subject, 0.3, frames=4)
    lost = subject.update(None, 400 * 1_000_000, S.SCROLL_MODE, POINTER, foreground=True)
    assert lost.notches == 0
    assert lost.rejection is ScrollRejection.POSE

    resumed = feed(subject, 0.3, start_ms=500, frames=3)
    assert all(update.notches == 0 for update in resumed)


def test_leaving_scroll_mode_stops_output_and_a_fresh_entry_waits() -> None:
    subject = controller()
    feed(subject, 0.3, frames=4)
    stopped = subject.update(
        0.3, 400 * 1_000_000, InteractionState.ACTIVE, POINTER, foreground=True
    )
    assert stopped.notches == 0
    assert stopped.rejection is ScrollRejection.STATE

    reentered = feed(subject, 0.3, start_ms=500, frames=2)
    assert all(update.notches == 0 for update in reentered)


@pytest.mark.parametrize(
    "kind", [TargetKind.PRESENTER_VIEW, TargetKind.EDIT_MODE, TargetKind.UNKNOWN]
)
def test_scroll_requires_scroll_capability(kind: TargetKind) -> None:
    subject = controller()
    updates = feed(subject, 0.0, frames=5, capabilities=capabilities_for(kind))
    assert all(update.rejection is ScrollRejection.CAPABILITY for update in updates)
    assert all(update.notches == 0 for update in updates)


def test_scroll_requires_foreground_focus() -> None:
    subject = controller()
    updates = feed(subject, 0.0, frames=5, foreground=False)
    assert all(update.rejection is ScrollRejection.FOCUS for update in updates)
    assert all(update.notches == 0 for update in updates)


def test_regaining_focus_waits_for_a_fresh_baseline() -> None:
    subject = controller()
    feed(subject, 0.0, frames=3)
    updates = feed(subject, 0.0, start_ms=300, frames=2, foreground=False)
    assert all(update.notches == 0 for update in updates)

    regained = feed(subject, 0.0, start_ms=500, frames=1)
    assert regained[0].notches == 0


def test_scroll_outside_scroll_mode_is_rejected_for_every_other_state() -> None:
    subject = controller()
    for state in InteractionState:
        if state is S.SCROLL_MODE:
            continue
        update = subject.update(0.0, 0, state, POINTER, foreground=True)
        assert update.rejection is ScrollRejection.STATE
        assert update.notches == 0


def test_invalid_settings_are_rejected() -> None:
    with pytest.raises(ValueError):
        controller(dead_zone=1.5)
    with pytest.raises(ValueError):
        controller(speed_notches_per_second=-1)
    with pytest.raises(ValueError):
        controller(max_notches_per_second=-1)
