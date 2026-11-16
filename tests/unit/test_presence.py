import inspect

from aircue.vision import presence
from aircue.vision.features import build_frame_record
from aircue.vision.presence import PresenceReporter
from aircue.vision.types import PresenceStatus
from tests.fixtures.landmarks import make_observation


def test_present_status_has_no_absence_run() -> None:
    reporter = PresenceReporter()
    status = reporter.observe(True, 100)
    assert status.present is True
    assert status.first_absence_ts_ns is None
    assert status.completed_absence_ns is None


def test_first_absence_timestamp_is_stable_during_run() -> None:
    reporter = PresenceReporter()
    first = reporter.observe(False, 100)
    later = reporter.observe(False, 450)
    assert first.first_absence_ts_ns == 100
    assert later.first_absence_ts_ns == 100
    assert later.absence_elapsed_ns(450) == 350


def test_presence_return_reports_completed_absence() -> None:
    reporter = PresenceReporter()
    reporter.observe(False, 100)
    reporter.observe(False, 550)
    returned = reporter.observe(True, 700)
    assert returned.present is True
    assert returned.completed_absence_ns == 600
    assert returned.first_absence_ts_ns is None


def test_state_layer_can_apply_freeze_and_idle_thresholds() -> None:
    reporter = PresenceReporter()
    status = reporter.observe(False, 1_000)
    assert status.absence_elapsed_ns(1_299) < 300
    assert status.absence_elapsed_ns(1_300) >= 300
    assert status.absence_elapsed_ns(1_999) < 1_000
    assert status.absence_elapsed_ns(2_000) >= 1_000

    present = PresenceStatus(present=True)
    assert present.absence_elapsed_ns(10_000) == 0


def test_vision_presence_does_not_import_or_change_state() -> None:
    source = inspect.getsource(presence)
    assert "aircue.state" not in source
    reporter = PresenceReporter()
    assert not hasattr(reporter, "state")
    reporter.observe(False, 1)
    assert not hasattr(reporter, "state")


def test_frame_record_carries_presence_status() -> None:
    reporter = PresenceReporter()
    status = reporter.observe(False, 500)
    record = build_frame_record(
        capture_ts_ns=500,
        frame_sequence=2,
        observation=None,
        hands_detected=0,
        confidence_threshold=0.5,
        finger_extended_angle_deg=160.0,
        presence=status,
    )
    assert record.presence is status
    assert record.hand is None
    assert record.presence.absence_elapsed_ns(1_500) == 1_000


def test_default_presence_follows_observation() -> None:
    present_record = build_frame_record(
        capture_ts_ns=1,
        frame_sequence=1,
        observation=make_observation(),
        hands_detected=1,
        confidence_threshold=0.5,
        finger_extended_angle_deg=160.0,
    )
    absent_record = build_frame_record(
        capture_ts_ns=2,
        frame_sequence=2,
        observation=None,
        hands_detected=0,
        confidence_threshold=0.5,
        finger_extended_angle_deg=160.0,
    )
    assert present_record.presence.present is True
    assert absent_record.presence.present is False
