from __future__ import annotations

import pytest

from aircue.state.machine import StateMachine
from aircue.state.safety import SafetyMonitor, TrackingStatus
from aircue.state.states import InteractionState
from aircue.state.transitions import TransitionTrigger

S = InteractionState
T = TransitionTrigger
ACTIVE_MODES = [S.ACTIVE, S.POINTER_MODE, S.SCROLL_MODE]


def ms(value: int) -> int:
    return value * 1_000_000


def monitor(**overrides) -> SafetyMonitor:
    settings = {"freeze_ms": 300, "idle_ms": 1000}
    settings.update(overrides)
    return SafetyMonitor(**settings)


def absent(subject: SafetyMonitor, start_ns: int, at_ns: int):
    assert subject.tracking(False, start_ns).status is TrackingStatus.BRIEF_LOSS
    return subject.tracking(False, at_ns)


def test_present_frames_are_tracked_and_not_frozen() -> None:
    subject = monitor()
    report = subject.tracking(True, 0)
    assert report.status is TrackingStatus.TRACKED
    assert report.absent_ns == 0
    assert report.output_frozen is False
    assert report.trigger is None


def test_output_freezes_on_the_first_absent_frame() -> None:
    subject = monitor()
    report = subject.tracking(False, 5_000_000)
    assert report.status is TrackingStatus.BRIEF_LOSS
    assert report.absent_ns == 0
    assert report.output_frozen is True
    assert report.trigger is None


def test_absence_duration_is_measured_from_the_first_absent_frame() -> None:
    subject = monitor()
    assert subject.tracking(False, ms(1)).absent_ns == 0
    assert subject.tracking(False, ms(101)).absent_ns == ms(100)
    assert subject.tracking(False, ms(501)).absent_ns == ms(500)


@pytest.mark.parametrize(
    ("absent_ms", "status"),
    [
        (0, TrackingStatus.BRIEF_LOSS),
        (299, TrackingStatus.BRIEF_LOSS),
        (300, TrackingStatus.EXTENDED_LOSS),
        (999, TrackingStatus.EXTENDED_LOSS),
        (1000, TrackingStatus.EXTENDED_LOSS),
        (1001, TrackingStatus.TIMED_OUT),
    ],
)
def test_status_boundaries(absent_ms: int, status: TrackingStatus) -> None:
    subject = monitor()
    report = absent(subject, 0, ms(absent_ms))
    assert report.status is status
    assert report.output_frozen is True


def test_timeout_trigger_fires_only_past_the_idle_window() -> None:
    subject = monitor()
    assert absent(subject, 0, ms(1000)).trigger is None
    report = absent(subject, 0, ms(1001))
    assert report.trigger is T.TRACKING_TIMEOUT


def test_timeout_trigger_fires_once_per_absence_episode() -> None:
    subject = monitor()
    absent(subject, 0, ms(1001))
    for timestamp in (1200, 1500, 3000):
        assert absent(subject, 0, ms(timestamp)).trigger is None
    assert subject.tracking(False, ms(4000)).output_frozen is True


def test_presence_restarts_the_absence_clock() -> None:
    subject = monitor()
    absent(subject, 0, ms(900))
    assert subject.tracking(True, ms(1000)).status is TrackingStatus.TRACKED

    report = subject.tracking(False, ms(5000))
    assert report.absent_ns == 0
    assert report.status is TrackingStatus.BRIEF_LOSS
    assert subject.tracking(False, ms(6001)).trigger is T.TRACKING_TIMEOUT


def test_timeout_fires_again_after_recovery_and_a_new_gap() -> None:
    subject = monitor()
    assert absent(subject, 0, ms(1001)).trigger is T.TRACKING_TIMEOUT
    assert subject.tracking(True, ms(1100)).status is TrackingStatus.TRACKED
    assert subject.tracking(False, ms(2000)).trigger is None
    assert subject.tracking(False, ms(3001)).trigger is T.TRACKING_TIMEOUT


@pytest.mark.parametrize("state", ACTIVE_MODES + [S.PAUSED])
def test_timeout_moves_each_source_state_to_idle(state: InteractionState) -> None:
    subject = monitor()
    trigger = absent(subject, 0, ms(1001)).trigger
    assert trigger is T.TRACKING_TIMEOUT

    machine = StateMachine(state)
    record = machine.apply(trigger, ms(1001))
    assert record.accepted is True
    assert machine.state is S.IDLE


@pytest.mark.parametrize("state", [S.IDLE, S.ERROR, S.EXITING, S.INITIALIZING])
def test_timeout_is_rejected_outside_the_listed_states(
    state: InteractionState,
) -> None:
    machine = StateMachine(state)
    record = machine.apply(T.TRACKING_TIMEOUT, ms(1001))
    assert record.accepted is False
    assert machine.state is state


def test_focus_loss_is_reported_once_per_loss() -> None:
    subject = monitor()
    assert subject.focus_changed(True) is None
    assert subject.focus_changed(False) is T.FOCUS_LOSS
    assert subject.focus_changed(False) is None
    assert subject.focus_changed(True) is None
    assert subject.focus_changed(False) is T.FOCUS_LOSS


@pytest.mark.parametrize("state", ACTIVE_MODES)
def test_focus_loss_moves_active_modes_to_paused(state: InteractionState) -> None:
    machine = StateMachine(state)
    record = machine.apply(T.FOCUS_LOSS, 0)
    assert record.accepted is True
    assert machine.state is S.PAUSED


def test_focus_loss_in_idle_is_a_noop() -> None:
    machine = StateMachine(S.IDLE)
    record = machine.apply(T.FOCUS_LOSS, 0)
    assert record.accepted is True
    assert record.resulting is S.IDLE
    assert machine.state is S.IDLE


@pytest.mark.parametrize("state", [S.PAUSED, S.ERROR, S.EXITING])
def test_focus_loss_has_no_transition_from_these_states(
    state: InteractionState,
) -> None:
    machine = StateMachine(state)
    record = machine.apply(T.FOCUS_LOSS, 0)
    assert record.accepted is False
    assert machine.state is state


def test_freeze_window_is_configurable() -> None:
    subject = monitor(freeze_ms=500, idle_ms=2000)
    assert absent(subject, 0, ms(499)).status is TrackingStatus.BRIEF_LOSS
    assert absent(subject, 0, ms(500)).status is TrackingStatus.EXTENDED_LOSS
    assert absent(subject, 0, ms(2000)).trigger is None
    assert absent(subject, 0, ms(2001)).trigger is T.TRACKING_TIMEOUT
