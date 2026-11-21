"""Non-activating status overlay: a layered, click-through Win32 window.

The state thread only publishes the newest status and posts a message. All
window creation, painting, and message pumping happen on a dedicated daemon
thread, so an unresponsive desktop or GDI call can never stall the state loop.
The window is ``WS_EX_NOACTIVATE`` and ``WS_EX_TRANSPARENT``: it never takes
focus and never receives mouse or keyboard input.
"""

from __future__ import annotations

import ctypes
import logging
import threading
from ctypes import wintypes

from aircue.state.feedback import StatusModel
from aircue.state.states import InteractionState

logger = logging.getLogger("aircue.ui")

_WS_POPUP = 0x80000000
_WS_EX_TOPMOST = 0x00000008
_WS_EX_TRANSPARENT = 0x00000020
_WS_EX_TOOLWINDOW = 0x00000080
_WS_EX_LAYERED = 0x00080000
_WS_EX_NOACTIVATE = 0x08000000

_WM_DESTROY = 0x0002
_WM_PAINT = 0x000F
_WM_CLOSE = 0x0010
_WM_MOUSEACTIVATE = 0x0021
_WM_NCHITTEST = 0x0084
_WM_APP = 0x8000

_HTTRANSPARENT = -1
_MA_NOACTIVATE = 3
_SW_SHOWNOACTIVATE = 4
_HWND_TOPMOST = -1
_SWP_NOMOVE = 0x0002
_SWP_NOSIZE = 0x0001
_SWP_NOACTIVATE = 0x0010
_SWP_SHOWWINDOW = 0x0040
_LWA_ALPHA = 0x00000002

_DT_LEFT = 0x0000
_DT_WORDBREAK = 0x0010
_DT_NOPREFIX = 0x0800
_TRANSPARENT = 1
_DEFAULT_CHARSET = 1
_SM_CXSCREEN = 0

_COLOR_BACKGROUND = 0x001E1E1E
_COLOR_IDLE = 0x00D8D8D8
_COLOR_ACTIVE = 0x008BE37C
_COLOR_ATTENTION = 0x0057C8FF
_ATTENTION_STATES = (InteractionState.PAUSED, InteractionState.ERROR)
_ACTIVE_STATES = (
    InteractionState.ACTIVE,
    InteractionState.POINTER_MODE,
    InteractionState.SCROLL_MODE,
)

_LRESULT = ctypes.c_ssize_t

_WNDPROC = ctypes.WINFUNCTYPE(
    _LRESULT, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM
)


class _WNDCLASSEXW(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.UINT),
        ("style", wintypes.UINT),
        ("lpfnWndProc", _WNDPROC),
        ("cbClsExtra", ctypes.c_int),
        ("cbWndExtra", ctypes.c_int),
        ("hInstance", wintypes.HINSTANCE),
        ("hIcon", wintypes.HICON),
        ("hCursor", wintypes.HANDLE),
        ("hbrBackground", wintypes.HBRUSH),
        ("lpszMenuName", wintypes.LPCWSTR),
        ("lpszClassName", wintypes.LPCWSTR),
        ("hIconSm", wintypes.HICON),
    ]


class _PAINTSTRUCT(ctypes.Structure):
    _fields_ = [
        ("hdc", wintypes.HDC),
        ("fErase", wintypes.BOOL),
        ("rcPaint", wintypes.RECT),
        ("fRestore", wintypes.BOOL),
        ("fIncUpdate", wintypes.BOOL),
        ("rgbReserved", wintypes.BYTE * 32),
    ]


_user32 = ctypes.WinDLL("user32", use_last_error=True)
_gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

_user32.RegisterClassExW.argtypes = [ctypes.POINTER(_WNDCLASSEXW)]
_user32.RegisterClassExW.restype = wintypes.ATOM
_user32.UnregisterClassW.argtypes = [wintypes.LPCWSTR, wintypes.HINSTANCE]
_user32.UnregisterClassW.restype = wintypes.BOOL
_user32.CreateWindowExW.argtypes = [
    wintypes.DWORD,
    wintypes.LPCWSTR,
    wintypes.LPCWSTR,
    wintypes.DWORD,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
    wintypes.HWND,
    wintypes.HMENU,
    wintypes.HINSTANCE,
    wintypes.LPVOID,
]
_user32.CreateWindowExW.restype = wintypes.HWND
_user32.DefWindowProcW.argtypes = [
    wintypes.HWND,
    wintypes.UINT,
    wintypes.WPARAM,
    wintypes.LPARAM,
]
_user32.DefWindowProcW.restype = _LRESULT
_user32.DestroyWindow.argtypes = [wintypes.HWND]
_user32.DestroyWindow.restype = wintypes.BOOL
_user32.PostQuitMessage.argtypes = [ctypes.c_int]
_user32.PostQuitMessage.restype = None
_user32.PostMessageW.argtypes = [
    wintypes.HWND,
    wintypes.UINT,
    wintypes.WPARAM,
    wintypes.LPARAM,
]
_user32.PostMessageW.restype = wintypes.BOOL
_user32.GetMessageW.argtypes = [
    ctypes.POINTER(wintypes.MSG),
    wintypes.HWND,
    wintypes.UINT,
    wintypes.UINT,
]
_user32.GetMessageW.restype = ctypes.c_int
_user32.TranslateMessage.argtypes = [ctypes.POINTER(wintypes.MSG)]
_user32.TranslateMessage.restype = wintypes.BOOL
_user32.DispatchMessageW.argtypes = [ctypes.POINTER(wintypes.MSG)]
_user32.DispatchMessageW.restype = _LRESULT
_user32.BeginPaint.argtypes = [wintypes.HWND, ctypes.POINTER(_PAINTSTRUCT)]
_user32.BeginPaint.restype = wintypes.HDC
_user32.EndPaint.argtypes = [wintypes.HWND, ctypes.POINTER(_PAINTSTRUCT)]
_user32.EndPaint.restype = wintypes.BOOL
_user32.GetClientRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
_user32.GetClientRect.restype = wintypes.BOOL
_user32.FillRect.argtypes = [wintypes.HDC, ctypes.POINTER(wintypes.RECT), wintypes.HBRUSH]
_user32.FillRect.restype = ctypes.c_int
_user32.DrawTextW.argtypes = [
    wintypes.HDC,
    wintypes.LPCWSTR,
    ctypes.c_int,
    ctypes.POINTER(wintypes.RECT),
    wintypes.UINT,
]
_user32.DrawTextW.restype = ctypes.c_int
_user32.InvalidateRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT), wintypes.BOOL]
_user32.InvalidateRect.restype = wintypes.BOOL
_user32.UpdateWindow.argtypes = [wintypes.HWND]
_user32.UpdateWindow.restype = wintypes.BOOL
_user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
_user32.ShowWindow.restype = wintypes.BOOL
_user32.SetLayeredWindowAttributes.argtypes = [
    wintypes.HWND,
    wintypes.DWORD,
    wintypes.BYTE,
    wintypes.DWORD,
]
_user32.SetLayeredWindowAttributes.restype = wintypes.BOOL
_user32.SetWindowPos.argtypes = [
    wintypes.HWND,
    wintypes.HWND,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
    wintypes.UINT,
]
_user32.SetWindowPos.restype = wintypes.BOOL
_user32.GetSystemMetrics.argtypes = [ctypes.c_int]
_user32.GetSystemMetrics.restype = ctypes.c_int

_gdi32.CreateSolidBrush.argtypes = [wintypes.DWORD]
_gdi32.CreateSolidBrush.restype = wintypes.HBRUSH
_gdi32.DeleteObject.argtypes = [wintypes.HANDLE]
_gdi32.DeleteObject.restype = wintypes.BOOL
_gdi32.SetBkMode.argtypes = [wintypes.HDC, ctypes.c_int]
_gdi32.SetBkMode.restype = ctypes.c_int
_gdi32.SetTextColor.argtypes = [wintypes.HDC, wintypes.DWORD]
_gdi32.SetTextColor.restype = wintypes.DWORD
_gdi32.CreateFontW.argtypes = [
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
    wintypes.DWORD,
    wintypes.DWORD,
    wintypes.DWORD,
    wintypes.DWORD,
    wintypes.DWORD,
    wintypes.DWORD,
    wintypes.DWORD,
    wintypes.DWORD,
    wintypes.LPCWSTR,
]
_gdi32.CreateFontW.restype = wintypes.HANDLE
_gdi32.SelectObject.argtypes = [wintypes.HDC, wintypes.HANDLE]
_gdi32.SelectObject.restype = wintypes.HANDLE

_kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
_kernel32.GetModuleHandleW.restype = wintypes.HINSTANCE

_CLASS_NAME = "AirCueStatusOverlay"


def format_status(status: StatusModel) -> str:
    """Render one status into the overlay's three display lines."""
    capabilities = [
        name
        for name, available in (
            ("navigation", status.capabilities.navigation),
            ("pointer", status.capabilities.pointer),
        )
        if available
    ]
    lines = [
        f"{status.state.value.upper()}  |  target: {status.target_kind.value}"
        f"  |  capabilities: {', '.join(capabilities) or 'none'}"
    ]
    if status.prompt:
        lines.append(status.prompt)
    if status.reason:
        lines.append(f"reason: {status.reason}")
    if status.warning:
        lines.append(f"warning: {status.warning}")
    return "\n".join(lines)


class Win32StatusOverlay:
    """Threaded status window that never activates and never eats input."""

    def __init__(
        self,
        *,
        width: int = 480,
        height: int = 112,
        margin: int = 16,
        opacity: float = 0.85,
    ) -> None:
        self._width = width
        self._height = height
        self._margin = margin
        self._alpha = round(max(0.1, min(1.0, opacity)) * 255)
        self._pending: StatusModel | None = None
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._hwnd = 0
        self._instance: int = 0
        self._ready = threading.Event()
        self._wndproc = _WNDPROC(self._window_proc)

    @property
    def hwnd(self) -> int:
        return self._hwnd

    def wait_until_ready(self, timeout: float = 2.0) -> bool:
        return self._ready.wait(timeout)

    def update(self, status: StatusModel) -> None:
        """Publish the latest status; returns without waiting for a paint."""
        with self._lock:
            self._pending = status
        if self._thread is None:
            self._thread = threading.Thread(
                target=self._run, name="aircue-overlay", daemon=True
            )
            self._thread.start()
        elif self._hwnd:
            _user32.PostMessageW(self._hwnd, _WM_APP, 0, 0)

    def close(self) -> None:
        """Ask the overlay thread to destroy its window, then join it."""
        thread = self._thread
        self._thread = None
        if thread is None:
            return
        self._ready.wait(1.0)
        if self._hwnd:
            _user32.PostMessageW(self._hwnd, _WM_CLOSE, 0, 0)
        thread.join(1.0)
        if thread.is_alive():
            logger.warning("status overlay did not close within 1 s")

    def _run(self) -> None:
        try:
            self._create_window()
            self._message_loop()
        except Exception:
            logger.exception("status overlay stopped after a window failure")
        finally:
            self._hwnd = 0
            self._ready.set()
            if self._instance:
                _user32.UnregisterClassW(_CLASS_NAME, self._instance)

    def _create_window(self) -> None:
        self._instance = _kernel32.GetModuleHandleW(None)
        window_class = _WNDCLASSEXW()
        window_class.cbSize = ctypes.sizeof(_WNDCLASSEXW)
        window_class.lpfnWndProc = self._wndproc
        window_class.hInstance = self._instance
        window_class.lpszClassName = _CLASS_NAME
        _user32.RegisterClassExW(ctypes.byref(window_class))

        screen_width = _user32.GetSystemMetrics(_SM_CXSCREEN)
        x = max(self._margin, (screen_width - self._width) // 2)
        extended = (
            _WS_EX_TOPMOST
            | _WS_EX_TRANSPARENT
            | _WS_EX_TOOLWINDOW
            | _WS_EX_LAYERED
            | _WS_EX_NOACTIVATE
        )
        hwnd = _user32.CreateWindowExW(
            extended,
            _CLASS_NAME,
            "AirCue",
            _WS_POPUP,
            x,
            self._margin,
            self._width,
            self._height,
            0,
            0,
            self._instance,
            0,
        )
        if not hwnd:
            raise ctypes.WinError(ctypes.get_last_error())
        self._hwnd = hwnd
        _user32.SetLayeredWindowAttributes(hwnd, 0, self._alpha, _LWA_ALPHA)
        _user32.ShowWindow(hwnd, _SW_SHOWNOACTIVATE)
        _user32.SetWindowPos(
            hwnd,
            _HWND_TOPMOST,
            0,
            0,
            0,
            0,
            _SWP_NOMOVE | _SWP_NOSIZE | _SWP_NOACTIVATE | _SWP_SHOWWINDOW,
        )
        _user32.UpdateWindow(hwnd)
        self._ready.set()

    def _message_loop(self) -> None:
        message = wintypes.MSG()
        while _user32.GetMessageW(ctypes.byref(message), 0, 0, 0) > 0:
            _user32.TranslateMessage(ctypes.byref(message))
            _user32.DispatchMessageW(ctypes.byref(message))

    def _window_proc(
        self,
        hwnd: int,
        message: int,
        wparam: int,
        lparam: int,
    ) -> int:
        if message == _WM_PAINT:
            self._paint(hwnd)
            return 0
        if message == _WM_APP:
            _user32.InvalidateRect(hwnd, None, True)
            return 0
        if message == _WM_NCHITTEST:
            return _HTTRANSPARENT
        if message == _WM_MOUSEACTIVATE:
            return _MA_NOACTIVATE
        if message == _WM_CLOSE:
            _user32.DestroyWindow(hwnd)
            return 0
        if message == _WM_DESTROY:
            _user32.PostQuitMessage(0)
            return 0
        return _user32.DefWindowProcW(hwnd, message, wparam, lparam)

    def _paint(self, hwnd: int) -> None:
        with self._lock:
            status = self._pending
        text = format_status(status) if status is not None else "AirCue starting..."
        state = status.state if status is not None else InteractionState.INITIALIZING

        paint = _PAINTSTRUCT()
        hdc = _user32.BeginPaint(hwnd, ctypes.byref(paint))
        try:
            rect = wintypes.RECT()
            _user32.GetClientRect(hwnd, ctypes.byref(rect))
            background = _gdi32.CreateSolidBrush(_COLOR_BACKGROUND)
            _user32.FillRect(hdc, ctypes.byref(rect), background)
            _gdi32.DeleteObject(background)

            _gdi32.SetBkMode(hdc, _TRANSPARENT)
            _gdi32.SetTextColor(hdc, self._text_color(state))
            font = _gdi32.CreateFontW(
                -18,
                0,
                0,
                0,
                500,
                0,
                0,
                0,
                _DEFAULT_CHARSET,
                0,
                0,
                0,
                0,
                "Segoe UI",
            )
            previous = _gdi32.SelectObject(hdc, font)
            text_rect = wintypes.RECT(16, 12, rect.right - 16, rect.bottom - 12)
            _user32.DrawTextW(
                hdc,
                text,
                len(text),
                ctypes.byref(text_rect),
                _DT_LEFT | _DT_WORDBREAK | _DT_NOPREFIX,
            )
            _gdi32.SelectObject(hdc, previous)
            _gdi32.DeleteObject(font)
        finally:
            _user32.EndPaint(hwnd, ctypes.byref(paint))

    @staticmethod
    def _text_color(state: InteractionState) -> int:
        if state in _ATTENTION_STATES:
            return _COLOR_ATTENTION
        if state in _ACTIVE_STATES:
            return _COLOR_ACTIVE
        return _COLOR_IDLE
