"""Presentation target kinds and their capabilities, per design.md D5."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class TargetKind(StrEnum):
    NORMAL_SLIDESHOW = "normal_slideshow"
    PRESENTER_VIEW = "presenter_view"
    EDIT_MODE = "edit_mode"
    UNKNOWN = "unknown"


class Capability(StrEnum):
    NAVIGATION = "navigation"
    POINTER = "pointer"


@dataclass(frozen=True)
class TargetCapabilities:
    navigation: bool = False
    pointer: bool = False

    def supports(self, capability: Capability) -> bool:
        return self.navigation if capability is Capability.NAVIGATION else self.pointer


_CAPABILITIES: dict[TargetKind, TargetCapabilities] = {
    TargetKind.NORMAL_SLIDESHOW: TargetCapabilities(navigation=True, pointer=True),
    TargetKind.PRESENTER_VIEW: TargetCapabilities(navigation=True),
    TargetKind.EDIT_MODE: TargetCapabilities(),
    TargetKind.UNKNOWN: TargetCapabilities(),
}


def capabilities_for(kind: TargetKind) -> TargetCapabilities:
    """Capabilities granted by a target kind. Edit mode and unknown grant none."""
    return _CAPABILITIES[kind]


def is_activatable(kind: TargetKind) -> bool:
    """Only an identified slideshow or presenter target may be activated."""
    return kind in (TargetKind.NORMAL_SLIDESHOW, TargetKind.PRESENTER_VIEW)


@dataclass(frozen=True)
class MonitorBounds:
    """A monitor rectangle in virtual-screen coordinates."""

    left: int
    top: int
    right: int
    bottom: int


@dataclass(frozen=True)
class TargetSnapshot:
    """A point-in-time description of the presentation target."""

    captured_ns: int
    kind: TargetKind = TargetKind.UNKNOWN
    capabilities: TargetCapabilities = TargetCapabilities()
    process_id: int | None = None
    window_handle: int | None = None
    output_handle: int | None = None
    monitor_bounds: MonitorBounds | None = None
    title: str | None = None

    def __post_init__(self) -> None:
        expected = capabilities_for(self.kind)
        if self.capabilities != expected:
            raise ValueError(f"{self.kind.value} must expose {expected}, not {self.capabilities}")

