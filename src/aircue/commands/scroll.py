"""Vertical hand displacement in SCROLL_MODE to bounded wheel notches."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from aircue.commands.commands import Command, CommandRejection
from aircue.commands.manager import CommandManager
from aircue.presentation.target import TargetCapabilities
from aircue.state.states import InteractionState

# A long frame gap must not dump a burst of wheel notches at once.
_MAX_FRAME_GAP_S = 0.1


class ScrollRejection(StrEnum):
    STATE = "state"
    CAPABILITY = "capability"
    FOCUS = "focus"
    POSE = "pose"


@dataclass(frozen=True)
class ScrollUpdate:
    """One scroll sample: wheel notches to emit, or why none may be emitted."""

    notches: int = 0
    rejection: ScrollRejection | None = None
    reason: str = ""

    @property
    def allowed(self) -> bool:
        return self.rejection is None


class ScrollController:
    """Maps vertical displacement to wheel notches, accumulating fractions.

    Only the first valid sample after entry or reset establishes the timing
    baseline, so entering the mode, reacquiring the hand, or regaining focus
    never emits scroll by itself. Displacement inside the dead zone stops and
    clears the accumulator. The rate is proportional to displacement and capped
    at ``max_notches_per_second``; positive notches scroll up.
    """

    def __init__(
        self,
        manager: CommandManager,
        *,
        dead_zone: float = 0.05,
        neutral_y: float = 0.5,
        speed_notches_per_second: float = 10.0,
        max_notches_per_second: float = 10.0,
        invert: bool = False,
    ) -> None:
        if not 0.0 <= dead_zone <= 1.0:
            raise ValueError("scroll dead_zone must be between 0 and 1")
        if speed_notches_per_second < 0 or max_notches_per_second < 0:
            raise ValueError("scroll rates must not be negative")
        self._manager = manager
        self._dead_zone = dead_zone
        self._neutral_y = neutral_y
        self._speed = speed_notches_per_second
        self._max_rate = max_notches_per_second
        self._invert = invert
        self._accumulator = 0.0
        self._direction = 0
        self._last_ns: int | None = None

    def reset(self) -> None:
        """Stop scrolling and require a fresh baseline before emitting again."""
        self._accumulator = 0.0
        self._direction = 0
        self._last_ns = None

    def update(
        self,
        y: float | None,
        timestamp_ns: int,
        state: InteractionState,
        capabilities: TargetCapabilities,
        *,
        foreground: bool,
    ) -> ScrollUpdate:
        decision = self._manager.validate(Command.SCROLL, state, capabilities)
        if decision.rejection is CommandRejection.STATE:
            self.reset()
            return ScrollUpdate(rejection=ScrollRejection.STATE, reason=decision.reason)
        if decision.rejection is CommandRejection.CAPABILITY:
            self.reset()
            return ScrollUpdate(
                rejection=ScrollRejection.CAPABILITY, reason=decision.reason
            )
        if not foreground:
            self.reset()
            return ScrollUpdate(
                rejection=ScrollRejection.FOCUS,
                reason="scroll requires a foreground presentation target",
            )
        if y is None:
            self.reset()
            return ScrollUpdate(
                rejection=ScrollRejection.POSE, reason="the scroll pose is not valid"
            )

        if self._last_ns is None:
            self._last_ns = timestamp_ns
            return ScrollUpdate()
        gap_s = min(max(timestamp_ns - self._last_ns, 0) / 1_000_000_000, _MAX_FRAME_GAP_S)
        self._last_ns = timestamp_ns

        displacement = y - self._neutral_y
        if abs(displacement) <= self._dead_zone:
            self._accumulator = 0.0
            self._direction = 0
            return ScrollUpdate()
        span = max(self._neutral_y, 1.0 - self._neutral_y) - self._dead_zone
        if span <= 0:
            self._accumulator = 0.0
            self._direction = 0
            return ScrollUpdate()
        strength = min((abs(displacement) - self._dead_zone) / span, 1.0)
        rate = min(self._speed * strength, self._max_rate)
        # Hand up means a smaller y; positive notches scroll up.
        direction = 1 if displacement < 0 else -1
        if self._invert:
            direction = -direction
        if direction != self._direction:
            self._accumulator = 0.0
            self._direction = direction
        self._accumulator += rate * gap_s

        notches = int(self._accumulator)
        if notches:
            self._accumulator -= notches
            return ScrollUpdate(notches=direction * notches)
        return ScrollUpdate()
