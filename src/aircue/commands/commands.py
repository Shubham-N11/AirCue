"""Command vocabulary and the recorded decision for one command."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from aircue.state.states import InteractionState


class Command(StrEnum):
    EXIT = "exit"
    PAUSE = "pause"
    RESUME = "resume"
    ACTIVATE = "activate"
    EXIT_POINTER_MODE = "exit_pointer_mode"
    EXIT_SCROLL_MODE = "exit_scroll_mode"
    ENTER_POINTER_MODE = "enter_pointer_mode"
    ENTER_SCROLL_MODE = "enter_scroll_mode"
    NEXT_SLIDE = "next_slide"
    PREVIOUS_SLIDE = "previous_slide"
    CLICK = "click"
    DOUBLE_CLICK = "double_click"
    SCROLL = "scroll"
    POINTER_MOVE = "pointer_move"


class CommandRejection(StrEnum):
    STATE = "state"
    CAPABILITY = "capability"


@dataclass(frozen=True)
class CommandDecision:
    """The gating outcome. A rejection has no presentation effect."""

    command: Command
    state: InteractionState
    rejection: CommandRejection | None = None
    reason: str = ""

    @property
    def allowed(self) -> bool:
        return self.rejection is None
