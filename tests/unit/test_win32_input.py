from __future__ import annotations

import pytest

from aircue.presentation import win32_input
from aircue.presentation.win32_input import (
    INPUT_KEYBOARD,
    INPUT_MOUSE,
    KEYEVENTF_KEYUP,
    MOUSEEVENTF_ABSOLUTE,
    MOUSEEVENTF_LEFTDOWN,
    MOUSEEVENTF_LEFTUP,
    MOUSEEVENTF_MOVE,
    MOUSEEVENTF_VIRTUALDESK,
    MOUSEEVENTF_WHEEL,
    SM_CXVIRTUALSCREEN,
    SM_CYVIRTUALSCREEN,
    SM_XVIRTUALSCREEN,
    SM_YVIRTUALSCREEN,
    VK_NEXT,
    CtypesInput,
)

PRIMARY = {
    SM_XVIRTUALSCREEN: 0,
    SM_YVIRTUALSCREEN: 0,
    SM_CXVIRTUALSCREEN: 1920,
    SM_CYVIRTUALSCREEN: 1080,
}
RIGHT_OF_PRIMARY = {
    SM_XVIRTUALSCREEN: 1920,
    SM_YVIRTUALSCREEN: 0,
    SM_CXVIRTUALSCREEN: 1920,
    SM_CYVIRTUALSCREEN: 1080,
}


class FakeUser32:
    def __init__(self, *, sent: int | None = None, metrics: dict[int, int] | None = None) -> None:
        self.calls: list[list] = []
        self.sent = sent
        self.metrics = dict(PRIMARY if metrics is None else metrics)

    def SendInput(self, count: int, events, size: int) -> int:
        self.calls.append(list(events))
        return count if self.sent is None else self.sent

    def GetSystemMetrics(self, index: int) -> int:
        return self.metrics[index]


def sink(monkeypatch: pytest.MonkeyPatch, **overrides) -> tuple[CtypesInput, FakeUser32]:
    api = FakeUser32(**overrides)
    monkeypatch.setattr(win32_input, "_user32", api)
    return CtypesInput(), api


def keys(events: list) -> list[tuple[int, int]]:
    return [(event.ki.wVk, event.ki.dwFlags) for event in events]


def test_key_sends_one_down_up_pair(monkeypatch: pytest.MonkeyPatch) -> None:
    subject, api = sink(monkeypatch)
    assert subject.key(VK_NEXT) is True
    assert len(api.calls) == 1
    assert keys(api.calls[0]) == [(VK_NEXT, 0), (VK_NEXT, KEYEVENTF_KEYUP)]
    assert {event.type for event in api.calls[0]} == {INPUT_KEYBOARD}


def test_a_short_send_is_a_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    subject, _ = sink(monkeypatch, sent=1)
    assert subject.key(VK_NEXT) is False


def test_move_normalizes_to_the_virtual_desktop(monkeypatch: pytest.MonkeyPatch) -> None:
    subject, api = sink(monkeypatch, metrics=RIGHT_OF_PRIMARY)
    assert subject.move(1920, 0) is True
    assert subject.move(3839, 1079) is True

    first, second = (call[0] for call in api.calls)
    assert (first.mi.dx, first.mi.dy) == (0, 0)
    assert (second.mi.dx, second.mi.dy) == (65535, 65535)
    assert first.mi.dwFlags == MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_VIRTUALDESK
    assert first.type == INPUT_MOUSE


def test_click_sends_one_left_down_up_pair(monkeypatch: pytest.MonkeyPatch) -> None:
    subject, api = sink(monkeypatch)
    assert subject.click(double=False) is True
    assert [event.mi.dwFlags for event in api.calls[0]] == [
        MOUSEEVENTF_LEFTDOWN,
        MOUSEEVENTF_LEFTUP,
    ]


def test_double_click_sends_two_left_down_up_pairs(monkeypatch: pytest.MonkeyPatch) -> None:
    subject, api = sink(monkeypatch)
    assert subject.click(double=True) is True
    assert [event.mi.dwFlags for event in api.calls[0]] == [
        MOUSEEVENTF_LEFTDOWN,
        MOUSEEVENTF_LEFTUP,
        MOUSEEVENTF_LEFTDOWN,
        MOUSEEVENTF_LEFTUP,
    ]


def test_wheel_sends_whole_notches(monkeypatch: pytest.MonkeyPatch) -> None:
    subject, api = sink(monkeypatch)
    assert subject.wheel(3) is True
    assert subject.wheel(-2) is True

    up, down = (call[0] for call in api.calls)
    assert up.mi.dwFlags == MOUSEEVENTF_WHEEL
    assert up.mi.mouseData == 360
    assert down.mi.mouseData == (-240) & 0xFFFFFFFF


def test_zero_notches_send_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    subject, api = sink(monkeypatch)
    assert subject.wheel(0) is True
    assert api.calls == []


def test_a_blocked_move_is_a_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    subject, _ = sink(monkeypatch, sent=0)
    assert subject.move(10, 20) is False
