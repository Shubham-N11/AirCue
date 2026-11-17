from __future__ import annotations

from dataclasses import dataclass

from aircue.presentation.target import ScreenRect
from aircue.presentation.win32 import (
    DiscoveryResult,
    PowerPointDiscovery,
    ProcessInfo,
    WindowCandidate,
)

PID = 100
PRIMARY = ScreenRect(0, 0, 1920, 1080)
SECONDARY = ScreenRect(1920, 0, 3840, 1080)


@dataclass(frozen=True)
class FakeWindow:
    process_id: int
    class_name: str = "screenClass"
    title: str = "Deck"
    visible: bool = True
    window_bounds: ScreenRect = PRIMARY
    monitor_bounds: ScreenRect = PRIMARY


class FakeWin32:
    def __init__(
        self,
        *,
        processes: tuple[ProcessInfo, ...] = (),
        windows: dict[int, FakeWindow] | None = None,
        foreground: int = 0,
        process_error: OSError | None = None,
        window_error: OSError | None = None,
        failing_handles: frozenset[int] = frozenset(),
    ) -> None:
        self.processes = processes
        self.windows = windows or {}
        self.foreground = foreground
        self.process_error = process_error
        self.window_error = window_error
        self.failing_handles = failing_handles

    def list_processes(self) -> tuple[ProcessInfo, ...]:
        if self.process_error is not None:
            raise self.process_error
        return self.processes

    def enumerate_windows(self) -> tuple[int, ...]:
        if self.window_error is not None:
            raise self.window_error
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
        if handle in self.failing_handles:
            raise OSError("access denied")
        return self.windows[handle].monitor_bounds


def window(process_id: int = PID, **overrides) -> FakeWindow:
    values = {
        "process_id": process_id,
        "class_name": "screenClass",
        "title": "Deck",
        "visible": True,
        "window_bounds": PRIMARY,
        "monitor_bounds": PRIMARY,
    }
    values.update(overrides)
    return FakeWindow(**values)


def discover(api: FakeWin32) -> DiscoveryResult:
    return PowerPointDiscovery(api).discover()


def test_no_powerpoint_process_is_unavailable() -> None:
    api = FakeWin32(
        processes=(ProcessInfo(1, "EXCEL.EXE"),),
        windows={1: window(1)},
    )
    result = discover(api)
    assert result.available is False
    assert result.processes == ()
    assert result.windows == ()
    assert result.errors == ()


def test_one_process_and_its_window_are_reported() -> None:
    api = FakeWin32(
        processes=(ProcessInfo(PID, "POWERPNT.EXE"),),
        windows={0x10: window(PID, title="Quarterly review", monitor_bounds=SECONDARY)},
        foreground=0x10,
    )
    result = discover(api)

    assert result.available is True
    assert result.processes == (ProcessInfo(PID, "POWERPNT.EXE"),)
    candidate = result.windows[0]
    assert candidate == WindowCandidate(
        process_id=PID,
        handle=0x10,
        class_name="screenClass",
        title="Quarterly review",
        visible=True,
        foreground=True,
        window_bounds=PRIMARY,
        monitor_bounds=SECONDARY,
    )
    assert result.errors == ()


def test_windows_from_other_processes_are_excluded() -> None:
    api = FakeWin32(
        processes=(
            ProcessInfo(PID, "POWERPNT.EXE"),
            ProcessInfo(200, "chrome.exe"),
        ),
        windows={1: window(PID), 2: window(200)},
    )
    result = discover(api)
    assert [candidate.handle for candidate in result.windows] == [1]
    assert result.windows[0].foreground is False


def test_multiple_powerpoint_processes_are_all_searched() -> None:
    api = FakeWin32(
        processes=(
            ProcessInfo(PID, "POWERPNT.EXE"),
            ProcessInfo(101, "powerpnt.exe"),
            ProcessInfo(200, "chrome.exe"),
        ),
        windows={1: window(PID), 2: window(101), 3: window(200)},
    )
    result = discover(api)
    assert [candidate.handle for candidate in result.windows] == [1, 2]
    assert {candidate.process_id for candidate in result.windows} == {PID, 101}


def test_hidden_windows_are_reported_but_not_visible() -> None:
    api = FakeWin32(
        processes=(ProcessInfo(PID, "POWERPNT.EXE"),),
        windows={1: window(PID, visible=False)},
    )
    result = discover(api)
    assert result.available is True
    assert len(result.windows) == 1
    assert result.windows[0].visible is False


def test_process_enumeration_failure_is_reported() -> None:
    api = FakeWin32(process_error=OSError("access denied"))
    result = discover(api)
    assert result.available is False
    assert result.windows == ()
    assert len(result.errors) == 1
    assert result.errors[0].startswith("process enumeration failed")


def test_window_enumeration_failure_keeps_processes() -> None:
    api = FakeWin32(
        processes=(ProcessInfo(PID, "POWERPNT.EXE"),),
        window_error=OSError("access denied"),
    )
    result = discover(api)
    assert result.available is True
    assert result.windows == ()
    assert len(result.errors) == 1
    assert result.errors[0].startswith("window enumeration failed")


def test_a_window_that_cannot_be_inspected_is_skipped_and_recorded() -> None:
    api = FakeWin32(
        processes=(ProcessInfo(PID, "POWERPNT.EXE"),),
        windows={1: window(PID), 2: window(PID)},
        failing_handles=frozenset({2}),
    )
    result = discover(api)
    assert [candidate.handle for candidate in result.windows] == [1]
    assert len(result.errors) == 1
    assert "0x2" in result.errors[0]
    assert "access denied" in result.errors[0]
