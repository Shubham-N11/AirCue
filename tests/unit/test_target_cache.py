from __future__ import annotations

from aircue.presentation.cache import TargetCache
from aircue.presentation.classify import SLIDESHOW_CLASS
from aircue.presentation.discovery import DiscoveryResult, ProcessInfo, WindowCandidate
from aircue.presentation.target import ScreenRect, TargetKind

PID = 100
PRIMARY = ScreenRect(0, 0, 1920, 1080)
SECONDARY = ScreenRect(1920, 0, 3840, 1080)


def ms(value: int) -> int:
    return value * 1_000_000


def window(handle: int, bounds: ScreenRect = PRIMARY) -> WindowCandidate:
    return WindowCandidate(
        process_id=PID,
        handle=handle,
        class_name=SLIDESHOW_CLASS,
        title="Deck",
        visible=True,
        foreground=True,
        window_bounds=bounds,
        monitor_bounds=bounds,
    )


def discovery(*windows: WindowCandidate) -> DiscoveryResult:
    return DiscoveryResult((ProcessInfo(PID, "POWERPNT.EXE"),), tuple(windows))


def cache(**overrides) -> TargetCache:
    settings = {"refresh_ms": 250, "stale_ms": 1000}
    settings.update(overrides)
    return TargetCache(**settings)


def test_nothing_is_fresh_before_the_first_refresh() -> None:
    subject = cache()
    snapshot = subject.snapshot(0)
    assert snapshot.kind is TargetKind.UNKNOWN
    assert snapshot.captured_ns == 0
    assert subject.is_fresh(0) is False
    assert subject.refresh_due(0) is True


def test_refresh_stores_the_classified_snapshot() -> None:
    subject = cache()
    snapshot = subject.refresh(discovery(window(7, SECONDARY)), ms(100))
    assert snapshot.kind is TargetKind.NORMAL_SLIDESHOW
    assert snapshot.process_id == PID
    assert snapshot.window_handle == 7
    assert snapshot.monitor_bounds == SECONDARY
    assert snapshot.captured_ns == ms(100)

    assert subject.snapshot(ms(100)) is snapshot
    assert subject.is_fresh(ms(100)) is True


def test_refresh_is_due_every_250_ms() -> None:
    subject = cache()
    subject.refresh(discovery(window(1)), 0)
    assert subject.refresh_due(ms(249)) is False
    assert subject.refresh_due(ms(250)) is True


def test_snapshot_is_fresh_up_to_one_second() -> None:
    subject = cache()
    stored = subject.refresh(discovery(window(1)), 0)
    assert subject.snapshot(ms(999)) is stored
    assert subject.snapshot(ms(1000)) is stored
    assert subject.is_fresh(ms(1000)) is True

    stale = subject.snapshot(ms(1001))
    assert stale.kind is TargetKind.UNKNOWN
    assert stale.capabilities.navigation is False
    assert stale.capabilities.pointer is False
    assert stale.captured_ns == 0
    assert subject.is_fresh(ms(1001)) is False
    assert subject.refresh_due(ms(1001)) is True


def test_refreshing_after_staleness_restores_a_fresh_target() -> None:
    subject = cache()
    subject.refresh(discovery(window(1)), 0)
    assert subject.snapshot(ms(1001)).kind is TargetKind.UNKNOWN

    refreshed = subject.refresh(discovery(window(2, SECONDARY)), ms(1001))
    assert refreshed.kind is TargetKind.NORMAL_SLIDESHOW
    assert refreshed.window_handle == 2
    assert refreshed.monitor_bounds == SECONDARY
    assert subject.snapshot(ms(1001)) is refreshed
    assert subject.snapshot(ms(2001)) is refreshed


def test_an_unknown_refresh_still_resets_the_refresh_clock() -> None:
    subject = cache()
    snapshot = subject.refresh(DiscoveryResult((), ()), 0)
    assert snapshot.kind is TargetKind.UNKNOWN
    assert subject.refresh_due(ms(249)) is False
    assert subject.refresh_due(ms(250)) is True
    assert subject.snapshot(ms(999)).kind is TargetKind.UNKNOWN


def test_unknown_after_staleness_keeps_the_original_capture_time() -> None:
    subject = cache()
    subject.refresh(discovery(window(1)), ms(50))
    stale = subject.snapshot(ms(1051))
    assert stale.captured_ns == ms(50)


def test_refresh_and_staleness_windows_are_configurable() -> None:
    subject = cache(refresh_ms=100, stale_ms=500)
    subject.refresh(discovery(window(1)), 0)
    assert subject.refresh_due(ms(99)) is False
    assert subject.refresh_due(ms(100)) is True
    assert subject.snapshot(ms(500)).kind is TargetKind.NORMAL_SLIDESHOW
    assert subject.snapshot(ms(501)).kind is TargetKind.UNKNOWN
