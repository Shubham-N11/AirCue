"""Windows-level checks for the non-activating status overlay."""

from __future__ import annotations

import ctypes
import time
from ctypes import wintypes

import pytest

from aircue.presentation.target import TargetKind, capabilities_for
from aircue.state.feedback import StatusModel
from aircue.state.states import InteractionState
from aircue.ui.overlay import Win32StatusOverlay

_WS_EX_TOPMOST = 0x00000008
_WS_EX_TRANSPARENT = 0x00000020
_WS_EX_TOOLWINDOW = 0x00000080
_WS_EX_LAYERED = 0x00080000
_WS_EX_NOACTIVATE = 0x08000000
_GWL_EXSTYLE = -20

_user32 = ctypes.WinDLL("user32", use_last_error=True)
_user32.WindowFromPoint.argtypes = [wintypes.POINT]
_user32.WindowFromPoint.restype = wintypes.HWND
_user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
_user32.GetWindowRect.restype = wintypes.BOOL
_user32.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
_user32.GetWindowLongW.restype = ctypes.c_long
_user32.GetForegroundWindow.argtypes = []
_user32.GetForegroundWindow.restype = wintypes.HWND
_user32.IsWindow.argtypes = [wintypes.HWND]
_user32.IsWindow.restype = wintypes.BOOL
_user32.IsWindowVisible.argtypes = [wintypes.HWND]
_user32.IsWindowVisible.restype = wintypes.BOOL


def active_status() -> StatusModel:
    return StatusModel(
        state=InteractionState.ACTIVE,
        target_kind=TargetKind.NORMAL_SLIDESHOW,
        capabilities=capabilities_for(TargetKind.NORMAL_SLIDESHOW),
    )


@pytest.fixture
def overlay() -> Win32StatusOverlay:
    subject = Win32StatusOverlay()
    try:
        yield subject
    finally:
        subject.close()


def test_overlay_is_visible_click_through_and_never_takes_focus(
    overlay: Win32StatusOverlay,
) -> None:
    foreground = _user32.GetForegroundWindow()
    overlay.update(active_status())
    assert overlay.wait_until_ready(2.0) is True
    hwnd = overlay.hwnd

    assert hwnd != 0
    assert _user32.IsWindowVisible(hwnd)
    assert _user32.GetForegroundWindow() == foreground

    extended = _user32.GetWindowLongW(hwnd, _GWL_EXSTYLE)
    for style in (
        _WS_EX_TOPMOST,
        _WS_EX_TRANSPARENT,
        _WS_EX_TOOLWINDOW,
        _WS_EX_LAYERED,
        _WS_EX_NOACTIVATE,
    ):
        assert extended & style, hex(style)

    rect = wintypes.RECT()
    assert _user32.GetWindowRect(hwnd, ctypes.byref(rect))
    center = wintypes.POINT(
        (rect.left + rect.right) // 2, (rect.top + rect.bottom) // 2
    )
    assert _user32.WindowFromPoint(center) != hwnd

    overlay.close()
    assert overlay.hwnd == 0
    assert not _user32.IsWindow(hwnd)


def test_updates_return_without_waiting_for_a_paint(
    overlay: Win32StatusOverlay,
) -> None:
    overlay.update(active_status())
    assert overlay.wait_until_ready(2.0) is True

    started = time.perf_counter()
    for state in (InteractionState.IDLE, InteractionState.PAUSED) * 10:
        overlay.update(
            StatusModel(
                state=state,
                target_kind=TargetKind.NORMAL_SLIDESHOW,
                capabilities=capabilities_for(TargetKind.NORMAL_SLIDESHOW),
                prompt="prompt",
                reason="reason",
            )
        )
    assert time.perf_counter() - started < 1.0
    assert _user32.IsWindowVisible(overlay.hwnd)
