"""Same-frame priority ordering for semantic gesture events."""

from __future__ import annotations

from collections.abc import Iterable

from aircue.gestures.semantic import GestureAction, SemanticEvent

# Order from design.md: exit, pause, resume or activation, mode exit, mode entry,
# slide navigation, click or double-click, scroll, pointer movement.
_PRIORITY_ORDER: tuple[tuple[GestureAction, ...], ...] = (
    (GestureAction.EXIT_REQUEST,),
    (GestureAction.PAUSE_TRACKING,),
    (GestureAction.RESUME_TRACKING, GestureAction.ACTIVATE),
    (GestureAction.EXIT_SCROLL_MODE, GestureAction.EXIT_POINTER_MODE),
    (GestureAction.ENTER_SCROLL_MODE, GestureAction.ENTER_POINTER_MODE),
    (GestureAction.NEXT_SLIDE, GestureAction.PREV_SLIDE),
    (GestureAction.CLICK_CANDIDATE, GestureAction.DOUBLE_CLICK),
    (GestureAction.SCROLL,),
    (GestureAction.POINTER_MOVEMENT,),
)

_RANKS = {
    action: (rank, position)
    for rank, group in enumerate(_PRIORITY_ORDER)
    for position, action in enumerate(group)
}


def priority_rank(action: GestureAction) -> tuple[int, int]:
    """Sort key for an action; earlier is more important."""
    return _RANKS[action]


def select_highest(candidates: Iterable[SemanticEvent]) -> SemanticEvent | None:
    """Return the highest-priority candidate for one frame, or None.

    Equal-rank actions use the fixed within-group order so contradictory
    pointer and scroll requests resolve deterministically.
    """
    return min(candidates, key=lambda event: priority_rank(event.action), default=None)
