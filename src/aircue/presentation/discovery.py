"""PowerPoint process and top-level-window discovery, free of Win32 imports."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from aircue.presentation.target import ScreenRect

POWERPOINT_EXECUTABLE = "POWERPNT.EXE"


@dataclass(frozen=True)
class ProcessInfo:
    process_id: int
    name: str


@dataclass(frozen=True)
class WindowCandidate:
    """One top-level window owned by a PowerPoint process."""

    process_id: int
    handle: int
    class_name: str
    title: str
    visible: bool
    foreground: bool
    window_bounds: ScreenRect
    monitor_bounds: ScreenRect


@dataclass(frozen=True)
class DiscoveryResult:
    processes: tuple[ProcessInfo, ...]
    windows: tuple[WindowCandidate, ...]
    errors: tuple[str, ...] = ()

    @property
    def available(self) -> bool:
        return bool(self.processes)


class Win32Api(Protocol):
    def list_processes(self) -> Sequence[ProcessInfo]: ...
    def enumerate_windows(self) -> Sequence[int]: ...
    def window_process_id(self, handle: int) -> int: ...
    def class_name(self, handle: int) -> str: ...
    def window_text(self, handle: int) -> str: ...
    def is_visible(self, handle: int) -> bool: ...
    def foreground_window(self) -> int: ...
    def window_rect(self, handle: int) -> ScreenRect: ...
    def monitor_rect(self, handle: int) -> ScreenRect: ...


class PowerPointDiscovery:
    """Reports PowerPoint processes and every top-level window they own.

    A window that cannot be inspected is skipped and recorded; discovery never
    guesses and never raises for an access failure.
    """

    def __init__(self, api: Win32Api) -> None:
        self._api = api

    def discover(self) -> DiscoveryResult:
        try:
            processes = tuple(
                process
                for process in self._api.list_processes()
                if process.name.upper() == POWERPOINT_EXECUTABLE
            )
        except OSError as error:
            return DiscoveryResult((), (), (f"process enumeration failed: {error}",))

        if not processes:
            return DiscoveryResult((), ())

        errors: list[str] = []
        try:
            handles = self._api.enumerate_windows()
        except OSError as error:
            return DiscoveryResult(processes, (), (f"window enumeration failed: {error}",))

        process_ids = {process.process_id for process in processes}
        foreground = self._api.foreground_window()
        windows: list[WindowCandidate] = []
        for handle in handles:
            try:
                process_id = self._api.window_process_id(handle)
                if process_id not in process_ids:
                    continue
                windows.append(
                    WindowCandidate(
                        process_id=process_id,
                        handle=handle,
                        class_name=self._api.class_name(handle),
                        title=self._api.window_text(handle),
                        visible=self._api.is_visible(handle),
                        foreground=handle == foreground,
                        window_bounds=self._api.window_rect(handle),
                        monitor_bounds=self._api.monitor_rect(handle),
                    )
                )
            except OSError as error:
                errors.append(f"window {handle:#x} access failed: {error}")
        return DiscoveryResult(processes, tuple(windows), tuple(errors))
