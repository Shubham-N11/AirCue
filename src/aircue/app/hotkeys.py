"""Configurable global shortcuts, polled on the state thread."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from aircue.config.schema import HotkeyConfig

VK_SHIFT = 0x10
VK_CONTROL = 0x11
VK_MENU = 0x12
VK_LWIN = 0x5B

_MODIFIERS = {
    "ctrl": VK_CONTROL,
    "control": VK_CONTROL,
    "alt": VK_MENU,
    "shift": VK_SHIFT,
    "win": VK_LWIN,
}
_NAMED_KEYS = {"space": 0x20, "tab": 0x09, "enter": 0x0D, "esc": 0x1B, "escape": 0x1B}


class HotkeyAction(StrEnum):
    ACTIVATE = "activate"
    DEACTIVATE = "deactivate"
    EXIT = "exit"


# Exit outranks every other shortcut, then deactivation, then activation.
_ORDER = (HotkeyAction.EXIT, HotkeyAction.DEACTIVATE, HotkeyAction.ACTIVATE)


@dataclass(frozen=True)
class Hotkey:
    key: int
    modifiers: frozenset[int] = frozenset()


def parse_hotkey(spec: str) -> Hotkey:
    """Parse ``ctrl+alt+a``-style text; raise ValueError on anything else."""
    parts = [part.strip().lower() for part in spec.split("+")]
    if not spec.strip() or any(not part for part in parts):
        raise ValueError(f"invalid hotkey {spec!r}")
    modifiers: set[int] = set()
    key: int | None = None
    for part in parts:
        if part in _MODIFIERS:
            modifiers.add(_MODIFIERS[part])
        elif key is None and part in _NAMED_KEYS:
            key = _NAMED_KEYS[part]
        elif key is None and len(part) == 1 and part.isalnum():
            key = ord(part.upper())
        else:
            raise ValueError(f"invalid hotkey {spec!r}: {part!r}")
    if key is None:
        raise ValueError(f"invalid hotkey {spec!r}: no key")
    return Hotkey(key, frozenset(modifiers))


class HotkeyPoller:
    """Turns global key state into one action per chord press.

    ``GetAsyncKeyState`` reports key state regardless of which window is
    foreground, so the shortcuts keep working while PowerPoint has focus. The
    poller latches each chord until it is released, so holding the keys does
    not repeat the action on every tick.
    """

    def __init__(self, config: HotkeyConfig, key_down: Callable[[int], bool]) -> None:
        self._key_down = key_down
        self._specs = {
            HotkeyAction.ACTIVATE: config.activate,
            HotkeyAction.DEACTIVATE: config.deactivate,
            HotkeyAction.EXIT: config.exit,
        }
        self._hotkeys = {
            action: parse_hotkey(spec) for action, spec in self._specs.items()
        }
        self._latched: set[HotkeyAction] = set()

    def spec(self, action: HotkeyAction) -> str:
        return self._specs[action]

    def poll(self) -> tuple[HotkeyAction, ...]:
        """Return the chords newly pressed since the previous poll."""
        fired: list[HotkeyAction] = []
        for action in _ORDER:
            hotkey = self._hotkeys[action]
            down = all(
                self._key_down(modifier) for modifier in hotkey.modifiers
            ) and self._key_down(hotkey.key)
            if not down:
                self._latched.discard(action)
            elif action not in self._latched:
                self._latched.add(action)
                fired.append(action)
        return tuple(fired)
