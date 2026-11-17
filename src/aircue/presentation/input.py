"""The input-synthesis port the presentation adapter drives."""

from __future__ import annotations

from typing import Protocol


class InputSink(Protocol):
    """Synthesizes one already-revalidated input action.

    Each method returns True only when the whole action was injected, so a
    partially blocked call is never reported as success.
    """

    def key(self, virtual_key: int) -> bool: ...

    def move(self, x: int, y: int) -> bool: ...

    def click(self, *, double: bool) -> bool: ...

    def wheel(self, notches: int) -> bool: ...
