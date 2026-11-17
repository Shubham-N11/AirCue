from __future__ import annotations

from dataclasses import dataclass

import pytest

from aircue.presentation.adapter import (
    AdapterError,
    AdapterResult,
    Click,
    CommandPayload,
    DoubleClick,
    Navigate,
    PointerMove,
    Scroll,
    SlideDirection,
)
from aircue.presentation.classify import EDITOR_CLASS, SLIDESHOW_CLASS
from aircue.presentation.discovery import ProcessInfo
from aircue.presentation.target import ScreenRect, TargetKind
from aircue.presentation.win32_adapter import Win32Adapter
from aircue.presentation.win32_input import VK_NEXT, VK_PRIOR

PID = 100
HANDLE = 0x10
PRIMARY = ScreenRect(0, 0, 1920, 1080)
SECONDARY = ScreenRect(1920, 0, 3840, 1080)
NEXT = Navigate(SlideDirection.NEXT)
PREVIOUS = Navigate(SlideDirection.PREVIOUS)
POINTER_PAYLOADS = [PointerMove(10, 20), Click(), DoubleClick(), Scroll(2)]


@dataclass(frozen=True)
class FakeWindow:
    process_id: int = PID
    class_name: str = SLIDESHOW_CLASS
    title: str = "Deck"
    visible: bool = True
    window_bounds: ScreenRect = PRIMARY
    monitor_bounds: ScreenRect = PRIMARY


class FakeWin32:
    def __init__(
        self,
        windows: dict[int, FakeWindow] | None = None,
        *,
        foreground: int = HANDLE,
        processes: tuple[ProcessInfo, ...] | None = None,
    ) -> None:
        self.windows = {HANDLE: FakeWindow()} if windows is None else windows
        self.foreground = foreground
        self.processes = (
            (ProcessInfo(PID, "POWERPNT.EXE"),) if processes is None else processes
        )

    def list_processes(self) -> tuple[ProcessInfo, ...]:
        return self.processes

    def enumerate_windows(self) -> tuple[int, ...]:
        return tuple(self.windows)

    def window_process_id(self, handle: int) -> int:
        return self.windows[handle].process_id

    def class_name(self, handle: int) -> str:
        return self.windows[handle].class_name

    def window_text(self, handle: int) -> str:
        return self.windows[handle].title

    def is_visible(self, handle: int) -> bool:
        return self.windows[handle].visible

    def foreground_window(self) -> int:
        return self.foreground

    def window_rect(self, handle: int) -> ScreenRect:
        return self.windows[handle].window_bounds

    def monitor_rect(self, handle: int) -> ScreenRect:
        return self.windows[handle].monitor_bounds


class RecordingSink:
    def __init__(self, *, accepted: bool = True) -> None:
        self.accepted = accepted
        self.calls: list[tuple[object, ...]] = []

    def key(self, virtual_key: int) -> bool:
        self.calls.append(("key", virtual_key))
        return self.accepted

    def move(self, x: int, y: int) -> bool:
        self.calls.append(("move", x, y))
        return self.accepted

    def click(self, *, double: bool) -> bool:
        self.calls.append(("click", double))
        return self.accepted

    def wheel(self, notches: int) -> bool:
        self.calls.append(("wheel", notches))
        return self.accepted


class Clock:
    def __init__(self) -> None:
        self.now = 0

    def __call__(self) -> int:
        return self.now


def ms(value: int) -> int:
    return value * 1_000_000


def build(
    windows: dict[int, FakeWindow] | None = None,
    *,
    foreground: int = HANDLE,
    processes: tuple[ProcessInfo, ...] | None = None,
) -> tuple[Win32Adapter, FakeWin32, RecordingSink, Clock]:
    api = FakeWin32(windows, foreground=foreground, processes=processes)
    sink = RecordingSink()
    clock = Clock()
    return Win32Adapter(api, sink, clock_ns=clock), api, sink, clock


def ready(
    windows: dict[int, FakeWindow] | None = None,
    *,
    expected: TargetKind = TargetKind.NORMAL_SLIDESHOW,
) -> tuple[Win32Adapter, FakeWin32, RecordingSink, Clock]:
    subject, api, sink, clock = build(windows)
    assert subject.refresh().kind is expected
    return subject, api, sink, clock


def normal_windows(bounds: ScreenRect = PRIMARY, **overrides) -> dict[int, FakeWindow]:
    return {
        HANDLE: FakeWindow(
            window_bounds=bounds, monitor_bounds=bounds, **overrides
        )
    }


def presenter_windows() -> dict[int, FakeWindow]:
    return {
        HANDLE: FakeWindow(class_name=EDITOR_CLASS, title="Presenter View - Deck"),
        HANDLE + 1: FakeWindow(window_bounds=SECONDARY, monitor_bounds=SECONDARY),
    }


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        (NEXT, ("key", VK_NEXT)),
        (PREVIOUS, ("key", VK_PRIOR)),
        (PointerMove(0x11, 0x22), ("move", 0x11, 0x22)),
        (Click(), ("click", False)),
        (DoubleClick(), ("click", True)),
        (Scroll(3), ("wheel", 3)),
        (Scroll(-2), ("wheel", -2)),
    ],
)
def test_each_payload_sends_exactly_one_action(
    payload: CommandPayload, expected: tuple[object, ...]
) -> None:
    subject, _, sink, _ = ready()
    assert subject.execute(payload) == AdapterResult()
    assert sink.calls == [expected]


def test_double_click_never_also_sends_a_single_click() -> None:
    subject, _, sink, _ = ready()
    assert subject.execute(DoubleClick()).ok is True
    assert sink.calls == [("click", True)]


def test_pointer_moves_to_the_slideshow_monitor() -> None:
    subject, _, sink, _ = ready(normal_windows(SECONDARY))
    assert subject.execute(PointerMove(2880, 540)).ok is True
    assert sink.calls == [("move", 2880, 540)]


def test_a_stale_target_rejects_without_input() -> None:
    subject, _, sink, clock = ready()
    clock.now = ms(1001)
    result = subject.execute(NEXT)
    assert result.error is AdapterError.TARGET_UNAVAILABLE
    assert sink.calls == []


def test_an_unknown_cached_target_rejects_without_input() -> None:
    subject, _, sink, _ = build(foreground=0)
    assert subject.refresh().kind is TargetKind.UNKNOWN
    result = subject.execute(NEXT)
    assert result.error is AdapterError.TARGET_UNAVAILABLE
    assert sink.calls == []


def test_edit_mode_rejects_every_payload() -> None:
    windows = {
        HANDLE: FakeWindow(
            class_name=EDITOR_CLASS,
            title="Deck - PowerPoint",
            window_bounds=ScreenRect(100, 100, 1500, 900),
        )
    }
    subject, _, sink, _ = ready(windows, expected=TargetKind.EDIT_MODE)
    for payload in [NEXT, *POINTER_PAYLOADS]:
        result = subject.execute(payload)
        assert result.error is AdapterError.TARGET_UNAVAILABLE
    assert sink.calls == []


def test_presenter_view_navigation_is_allowed() -> None:
    subject, _, sink, _ = ready(
        presenter_windows(), expected=TargetKind.PRESENTER_VIEW
    )
    assert subject.execute(PREVIOUS).ok is True
    assert sink.calls == [("key", VK_PRIOR)]


def test_presenter_view_rejects_all_pointer_input() -> None:
    subject, _, sink, _ = ready(
        presenter_windows(), expected=TargetKind.PRESENTER_VIEW
    )
    for payload in POINTER_PAYLOADS:
        result = subject.execute(payload)
        assert result.error is AdapterError.UNSUPPORTED_PRESENTER_VIEW
    assert sink.calls == []


def test_focus_lost_before_synthesis_rejects_without_input() -> None:
    subject, api, sink, _ = ready()
    api.foreground = 0
    result = subject.execute(NEXT)
    assert result.error is AdapterError.FOCUS_LOST
    assert sink.calls == []


def test_a_changed_window_handle_rejects_without_input() -> None:
    subject, api, sink, _ = ready()
    api.windows = {HANDLE + 1: FakeWindow()}
    api.foreground = HANDLE + 1
    result = subject.execute(NEXT)
    assert result.error is AdapterError.TARGET_CHANGED
    assert "foreground" in result.detail
    assert sink.calls == []


def test_a_changed_process_rejects_without_input() -> None:
    subject, api, sink, _ = ready()
    api.processes = (ProcessInfo(PID + 1, "POWERPNT.EXE"),)
    api.windows = normal_windows(process_id=PID + 1)
    result = subject.execute(NEXT)
    assert result.error is AdapterError.TARGET_CHANGED
    assert "process" in result.detail
    assert sink.calls == []


def test_changed_monitor_bounds_reject_without_input() -> None:
    subject, api, sink, _ = ready()
    api.windows = normal_windows(SECONDARY)
    result = subject.execute(NEXT)
    assert result.error is AdapterError.TARGET_CHANGED
    assert "monitor" in result.detail
    assert sink.calls == []


def test_a_changed_target_kind_rejects_without_input() -> None:
    subject, api, sink, _ = ready()
    api.windows = {
        HANDLE: FakeWindow(
            class_name=EDITOR_CLASS,
            title="Deck - PowerPoint",
            window_bounds=ScreenRect(100, 100, 1500, 900),
        )
    }
    result = subject.execute(NEXT)
    assert result.error is AdapterError.TARGET_CHANGED
    assert "kind" in result.detail
    assert sink.calls == []


def test_an_ambiguous_foreground_rejects_without_input() -> None:
    subject, api, sink, _ = ready()
    api.windows = {HANDLE: FakeWindow(class_name="SomeOtherClass")}
    result = subject.execute(NEXT)
    assert result.error is AdapterError.TARGET_UNAVAILABLE
    assert sink.calls == []


def test_powerpoint_closure_is_adapter_unavailable() -> None:
    subject, api, sink, _ = ready()
    api.processes = ()
    result = subject.execute(NEXT)
    assert result.error is AdapterError.ADAPTER_UNAVAILABLE
    assert "PowerPoint is not running" in result.detail
    assert sink.calls == []


def test_blocked_send_is_reported_as_input_blocked() -> None:
    subject, _, sink, _ = ready()
    sink.accepted = False
    result = subject.execute(NEXT)
    assert result.error is AdapterError.INPUT_BLOCKED
    assert len(sink.calls) == 1


def test_pointer_outside_the_revalidated_monitor_rejects_without_input() -> None:
    subject, _, sink, _ = ready(normal_windows(SECONDARY))
    result = subject.execute(PointerMove(10, 10))
    assert result.error is AdapterError.TARGET_CHANGED
    assert "outside the slideshow monitor" in result.detail
    assert sink.calls == []


def test_snapshot_and_refresh_follow_the_cache() -> None:
    subject, _, _, clock = build()
    assert subject.snapshot().kind is TargetKind.UNKNOWN

    refreshed = subject.refresh()
    assert refreshed.kind is TargetKind.NORMAL_SLIDESHOW
    assert subject.snapshot() is refreshed

    clock.now = ms(1001)
    assert subject.snapshot().kind is TargetKind.UNKNOWN


def test_the_adapter_satisfies_the_presentation_contract() -> None:
    from aircue.presentation.adapter import PresentationAdapter

    subject, _, _, _ = build()
    assert isinstance(subject, PresentationAdapter)
