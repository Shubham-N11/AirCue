"""The real Win32 API behind the discovery protocol."""

from __future__ import annotations

import ctypes
from ctypes import wintypes

from aircue.presentation.discovery import ProcessInfo
from aircue.presentation.target import ScreenRect

_TH32CS_SNAPPROCESS = 0x00000002
_MONITOR_DEFAULTTONEAREST = 0x00000002
_MAX_PATH = 260
_INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value


class _PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD),
        ("cntUsage", wintypes.DWORD),
        ("th32ProcessID", wintypes.DWORD),
        ("th32DefaultHeapID", ctypes.c_size_t),
        ("th32ModuleID", wintypes.DWORD),
        ("cntThreads", wintypes.DWORD),
        ("th32ParentProcessID", wintypes.DWORD),
        ("pcPriClassBase", ctypes.c_long),
        ("dwFlags", wintypes.DWORD),
        ("szExeFile", wintypes.WCHAR * _MAX_PATH),
    ]


class _MONITORINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("rcMonitor", wintypes.RECT),
        ("rcWork", wintypes.RECT),
        ("dwFlags", wintypes.DWORD),
    ]


_WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
_user32 = ctypes.WinDLL("user32", use_last_error=True)

_kernel32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
_kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
_kernel32.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.POINTER(_PROCESSENTRY32W)]
_kernel32.Process32FirstW.restype = wintypes.BOOL
_kernel32.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(_PROCESSENTRY32W)]
_kernel32.Process32NextW.restype = wintypes.BOOL
_kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
_kernel32.CloseHandle.restype = wintypes.BOOL

_user32.EnumWindows.argtypes = [_WNDENUMPROC, wintypes.LPARAM]
_user32.EnumWindows.restype = wintypes.BOOL
_user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
_user32.GetWindowThreadProcessId.restype = wintypes.DWORD
_user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
_user32.GetClassNameW.restype = ctypes.c_int
_user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
_user32.GetWindowTextW.restype = ctypes.c_int
_user32.IsWindowVisible.argtypes = [wintypes.HWND]
_user32.IsWindowVisible.restype = wintypes.BOOL
_user32.GetForegroundWindow.argtypes = []
_user32.GetForegroundWindow.restype = wintypes.HWND
_user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
_user32.GetWindowRect.restype = wintypes.BOOL
_user32.MonitorFromWindow.argtypes = [wintypes.HWND, wintypes.DWORD]
_user32.MonitorFromWindow.restype = wintypes.HMONITOR
_user32.GetMonitorInfoW.argtypes = [wintypes.HMONITOR, ctypes.POINTER(_MONITORINFO)]
_user32.GetMonitorInfoW.restype = wintypes.BOOL


class CtypesWin32:
    """The real Win32 API behind the discovery protocol."""

    def list_processes(self) -> tuple[ProcessInfo, ...]:
        snapshot = _kernel32.CreateToolhelp32Snapshot(_TH32CS_SNAPPROCESS, 0)
        if snapshot == _INVALID_HANDLE_VALUE:
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            entry = _PROCESSENTRY32W()
            entry.dwSize = ctypes.sizeof(_PROCESSENTRY32W)
            if not _kernel32.Process32FirstW(snapshot, ctypes.byref(entry)):
                raise ctypes.WinError(ctypes.get_last_error())
            processes: list[ProcessInfo] = []
            while True:
                processes.append(ProcessInfo(entry.th32ProcessID, entry.szExeFile))
                if not _kernel32.Process32NextW(snapshot, ctypes.byref(entry)):
                    break
            return tuple(processes)
        finally:
            _kernel32.CloseHandle(snapshot)

    def enumerate_windows(self) -> tuple[int, ...]:
        handles: list[int] = []

        def collect(handle: int, _lparam: int) -> bool:
            handles.append(int(handle))
            return True

        if not _user32.EnumWindows(_WNDENUMPROC(collect), 0):
            raise ctypes.WinError(ctypes.get_last_error())
        return tuple(handles)

    def window_process_id(self, handle: int) -> int:
        process_id = wintypes.DWORD()
        _user32.GetWindowThreadProcessId(handle, ctypes.byref(process_id))
        return int(process_id.value)

    def class_name(self, handle: int) -> str:
        buffer = ctypes.create_unicode_buffer(256)
        _user32.GetClassNameW(handle, buffer, len(buffer))
        return buffer.value

    def window_text(self, handle: int) -> str:
        buffer = ctypes.create_unicode_buffer(512)
        _user32.GetWindowTextW(handle, buffer, len(buffer))
        return buffer.value

    def is_visible(self, handle: int) -> bool:
        return bool(_user32.IsWindowVisible(handle))

    def foreground_window(self) -> int:
        return int(_user32.GetForegroundWindow() or 0)

    def window_rect(self, handle: int) -> ScreenRect:
        rect = wintypes.RECT()
        if not _user32.GetWindowRect(handle, ctypes.byref(rect)):
            raise ctypes.WinError(ctypes.get_last_error())
        return ScreenRect(rect.left, rect.top, rect.right, rect.bottom)

    def monitor_rect(self, handle: int) -> ScreenRect:
        monitor = _user32.MonitorFromWindow(handle, _MONITOR_DEFAULTTONEAREST)
        if not monitor:
            raise ctypes.WinError(ctypes.get_last_error())
        info = _MONITORINFO()
        info.cbSize = ctypes.sizeof(_MONITORINFO)
        if not _user32.GetMonitorInfoW(monitor, ctypes.byref(info)):
            raise ctypes.WinError(ctypes.get_last_error())
        rect = info.rcMonitor
        return ScreenRect(rect.left, rect.top, rect.right, rect.bottom)
