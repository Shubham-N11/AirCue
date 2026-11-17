"""Adapter protocol and the only payloads the adapter may execute.

The command layer validates a semantic command, then converts it to one of these
payloads. A raw command enum is not a payload, so an ungated command cannot be
handed to the adapter.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol, runtime_checkable

from aircue.presentation.target import TargetSnapshot


class SlideDirection(StrEnum):
    NEXT = "next"
    PREVIOUS = "previous"


@dataclass(frozen=True)
class Navigate:
    direction: SlideDirection


@dataclass(frozen=True)
class PointerMove:
    """Absolute virtual-screen coordinates on the slideshow monitor."""

    x: int
    y: int


@dataclass(frozen=True)
class Click:
    pass


@dataclass(frozen=True)
class DoubleClick:
    pass


@dataclass(frozen=True)
class Scroll:
    """Vertical wheel notches; positive scrolls up."""

    notches: int


CommandPayload = Navigate | PointerMove | Click | DoubleClick | Scroll


class AdapterError(StrEnum):
    FOCUS_LOST = "focus_lost"
    TARGET_CHANGED = "target_changed"
    TARGET_UNAVAILABLE = "target_unavailable"
    UNSUPPORTED_PRESENTER_VIEW = "unsupported_presenter_view"
    STALE_COMMAND = "stale_command"
    INPUT_BLOCKED = "input_blocked"
    ADAPTER_UNAVAILABLE = "adapter_unavailable"
    TIMEOUT = "timeout"
    INTERNAL = "internal"


@dataclass(frozen=True)
class AdapterResult:
    """What one adapter call did; an error means no input was sent."""

    error: AdapterError | None = None
    detail: str = ""

    @property
    def ok(self) -> bool:
        return self.error is None


@runtime_checkable
class PresentationAdapter(Protocol):
    def snapshot(self) -> TargetSnapshot:
        """Return the latest cached target; never blocks on Win32."""
        ...

    def refresh(self) -> TargetSnapshot:
        """Rediscover the target on the command worker and cache the result."""
        ...

    def execute(self, payload: CommandPayload) -> AdapterResult:
        """Synthesize one already-validated command after revalidating the target."""
        ...
