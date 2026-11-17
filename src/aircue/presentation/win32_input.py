"""ctypes SendInput synthesis for the Win32 adapter."""

from __future__ import annotations

import ctypes
from ctypes import wintypes

WHEEL_DELTA = 120
VK_PRIOR = 0x21
VK_NEXT = 0x22

INPUT_MOUSE = 0
INPUT_KEYBOARD = 1
KEYEVENTF_KEYUP = 0x0002
MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_WHEEL = 0x0800
MOUSEEVENTF_VIRTUALDESK = 0x4000
MOUSEEVENTF_ABSOLUTE = 0x8000

SM_XVIRTUALSCREEN = 76
SM_YVIRTUALSCREEN = 77
SM_CXVIRTUALSCREEN = 78
SM_CYVIRTUALSCREEN = 79

_ABSOLUTE_MAX = 65535
# ctypes.wintypes has no ULONG_PTR on this host; size_t has the same width.
_EXTRA_INFO = ctypes.c_size_t


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", _EXTRA_INFO),
    ]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", _EXTRA_INFO),
    ]


class _INPUTUNION(ctypes.Union):
    _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT)]


class INPUT(ctypes.Structure):
    _anonymous_ = ("u",)
    _fields_ = [("type", wintypes.DWORD), ("u", _INPUTUNION)]


_user32 = ctypes.WinDLL("user32", use_last_error=True)
_user32.SendInput.argtypes = [wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int]
_user32.SendInput.restype = wintypes.UINT
_user32.GetSystemMetrics.argtypes = [ctypes.c_int]
_user32.GetSystemMetrics.restype = ctypes.c_int


def _key_event(virtual_key: int, flags: int) -> INPUT:
    return INPUT(type=INPUT_KEYBOARD, u=_INPUTUNION(ki=KEYBDINPUT(virtual_key, 0, flags, 0, 0)))


def _mouse_event(dx: int, dy: int, data: int, flags: int) -> INPUT:
    return INPUT(type=INPUT_MOUSE, u=_INPUTUNION(mi=MOUSEINPUT(dx, dy, data, flags, 0, 0)))


def _normalize(position: int, span: int) -> int:
    if span <= 1:
        return 0
    scaled = round(position * _ABSOLUTE_MAX / (span - 1))
    return max(0, min(_ABSOLUTE_MAX, scaled))


class CtypesInput:
    """Synthesizes input through SendInput; any short call reports False."""

    def key(self, virtual_key: int) -> bool:
        return self._send(
            _key_event(virtual_key, 0),
            _key_event(virtual_key, KEYEVENTF_KEYUP),
        )

    def move(self, x: int, y: int) -> bool:
        left = _user32.GetSystemMetrics(SM_XVIRTUALSCREEN)
        top = _user32.GetSystemMetrics(SM_YVIRTUALSCREEN)
        width = _user32.GetSystemMetrics(SM_CXVIRTUALSCREEN)
        height = _user32.GetSystemMetrics(SM_CYVIRTUALSCREEN)
        return self._send(
            _mouse_event(
                _normalize(x - left, width),
                _normalize(y - top, height),
                0,
                MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_VIRTUALDESK,
            )
        )

    def click(self, *, double: bool) -> bool:
        events = (
            _mouse_event(0, 0, 0, MOUSEEVENTF_LEFTDOWN),
            _mouse_event(0, 0, 0, MOUSEEVENTF_LEFTUP),
        )
        return self._send(*(events * 2 if double else events))

    def wheel(self, notches: int) -> bool:
        if notches == 0:
            return True
        data = (notches * WHEEL_DELTA) & 0xFFFFFFFF
        return self._send(_mouse_event(0, 0, data, MOUSEEVENTF_WHEEL))

    @staticmethod
    def _send(*events: INPUT) -> bool:
        if not events:
            return True
        array = (INPUT * len(events))(*events)
        sent = _user32.SendInput(len(events), array, ctypes.sizeof(INPUT))
        return sent == len(events)
