from __future__ import annotations

import pytest

from aircue.app.hotkeys import (
    VK_CONTROL,
    VK_MENU,
    VK_SHIFT,
    Hotkey,
    HotkeyAction,
    HotkeyPoller,
    parse_hotkey,
)
from aircue.config.schema import HotkeyConfig


class Keys:
    def __init__(self, *down: int) -> None:
        self.down = set(down)

    def pressed(self, virtual_key: int) -> bool:
        return virtual_key in self.down


def poller(keys: Keys) -> HotkeyPoller:
    return HotkeyPoller(HotkeyConfig(), keys.pressed)


def test_default_shortcuts_parse_to_modifiers_and_one_key() -> None:
    assert parse_hotkey("ctrl+alt+a") == Hotkey(
        ord("A"), frozenset({VK_CONTROL, VK_MENU})
    )
    assert parse_hotkey("ctrl+shift+q") == Hotkey(
        ord("Q"), frozenset({VK_CONTROL, VK_SHIFT})
    )
    assert parse_hotkey("alt+space") == Hotkey(0x20, frozenset({VK_MENU}))


@pytest.mark.parametrize(
    "spec", ["", "ctrl+alt", "ctrl+alt+", "hyper+a", "ctrl+a+b", "ctrl+alt+aa"]
)
def test_invalid_shortcuts_are_rejected(spec: str) -> None:
    with pytest.raises(ValueError):
        parse_hotkey(spec)


def test_a_held_chord_fires_once_and_rearms_after_release() -> None:
    keys = Keys(VK_CONTROL, VK_MENU)
    subject = poller(keys)

    assert subject.poll() == ()

    keys.down.add(ord("A"))
    assert subject.poll() == (HotkeyAction.ACTIVATE,)
    assert subject.poll() == ()

    keys.down.discard(ord("A"))
    assert subject.poll() == ()
    keys.down.add(ord("A"))
    assert subject.poll() == (HotkeyAction.ACTIVATE,)


def test_every_modifier_is_required() -> None:
    keys = Keys(VK_CONTROL, ord("A"))
    assert poller(keys).poll() == ()


def test_simultaneous_chords_are_reported_exit_first() -> None:
    keys = Keys(VK_CONTROL, VK_MENU, ord("A"), ord("D"), ord("Q"))
    assert poller(keys).poll() == (
        HotkeyAction.EXIT,
        HotkeyAction.DEACTIVATE,
        HotkeyAction.ACTIVATE,
    )
