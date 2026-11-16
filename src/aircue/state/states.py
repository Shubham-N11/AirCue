"""Interaction states. The transition table lands with the state layer."""

from __future__ import annotations

from enum import StrEnum


class InteractionState(StrEnum):
    INITIALIZING = "initializing"
    IDLE = "idle"
    ACTIVE = "active"
    PAUSED = "paused"
    POINTER_MODE = "pointer_mode"
    SCROLL_MODE = "scroll_mode"
    ERROR = "error"
    EXITING = "exiting"
