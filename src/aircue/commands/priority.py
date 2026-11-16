"""Same-window command priority, from design.md D3 and the interaction-state spec."""

from __future__ import annotations

from collections.abc import Iterable

from aircue.commands.commands import Command

PRIORITY: tuple[tuple[Command, ...], ...] = (
    (Command.EXIT,),
    (Command.PAUSE,),
    (Command.RESUME, Command.ACTIVATE),
    (Command.EXIT_SCROLL_MODE, Command.EXIT_POINTER_MODE),
    (Command.ENTER_SCROLL_MODE, Command.ENTER_POINTER_MODE),
    (Command.NEXT_SLIDE, Command.PREVIOUS_SLIDE),
    (Command.CLICK, Command.DOUBLE_CLICK),
    (Command.SCROLL,),
    (Command.POINTER_MOVE,),
)

_RANKS = {
    command: (rank, position)
    for rank, group in enumerate(PRIORITY)
    for position, command in enumerate(group)
}


def priority_rank(command: Command) -> tuple[int, int]:
    """Sort key for a command; earlier is more important."""
    return _RANKS[command]


def highest_priority(commands: Iterable[Command]) -> Command | None:
    """Return the most important command in one processing window, or None."""
    return min(commands, key=priority_rank, default=None)
