"""Atomic application of the authoritative transition table."""

from __future__ import annotations

from dataclasses import dataclass

from aircue.state.states import InteractionState
from aircue.state.transitions import (
    Termination,
    Transition,
    TransitionTrigger,
    find_transition,
)


@dataclass(frozen=True)
class TransitionRecord:
    """What one apply call did: accepted, or rejected with no state change."""

    accepted: bool
    previous: InteractionState
    trigger: TransitionTrigger
    resulting: InteractionState
    reason: str
    generation: int
    timestamp_ns: int
    terminated: bool = False


class StateMachine:
    """Applies only the transitions listed in design.md D3.1.

    An accepted transition increments the generation exactly once and advances
    the monotonic timestamp. A rejected trigger returns a record with the state
    and generation untouched, so callers can log it without side effects.
    """

    def __init__(self, initial: InteractionState = InteractionState.INITIALIZING) -> None:
        self._state = initial
        self._generation = 0
        self._last_timestamp_ns: int | None = None
        self._terminated = False

    @property
    def state(self) -> InteractionState:
        return self._state

    @property
    def generation(self) -> int:
        return self._generation

    @property
    def terminated(self) -> bool:
        return self._terminated

    def is_stale(self, generation: int) -> bool:
        """True when work captured under this generation must not be dispatched."""
        return generation != self._generation

    def apply(
        self,
        trigger: TransitionTrigger,
        timestamp_ns: int,
        *,
        reason: str | None = None,
    ) -> TransitionRecord:
        previous = self._state
        transition = None if self._terminated else find_transition(previous, trigger)

        rejection = self._rejection(transition, timestamp_ns)
        if rejection is not None:
            return TransitionRecord(
                accepted=False,
                previous=previous,
                trigger=trigger,
                resulting=previous,
                reason=rejection,
                generation=self._generation,
                timestamp_ns=timestamp_ns,
            )

        assert transition is not None
        self._generation += 1
        self._last_timestamp_ns = timestamp_ns
        applied_reason = trigger.value if reason is None else reason
        if isinstance(transition.target, Termination):
            self._terminated = True
            return TransitionRecord(
                accepted=True,
                previous=previous,
                trigger=trigger,
                resulting=previous,
                reason=applied_reason,
                generation=self._generation,
                timestamp_ns=timestamp_ns,
                terminated=True,
            )
        self._state = transition.target
        return TransitionRecord(
            accepted=True,
            previous=previous,
            trigger=trigger,
            resulting=transition.target,
            reason=applied_reason,
            generation=self._generation,
            timestamp_ns=timestamp_ns,
        )

    def _rejection(self, transition: Transition | None, timestamp_ns: int) -> str | None:
        if self._terminated:
            return "runtime already terminated"
        if transition is None:
            return f"trigger not permitted from {self._state.value}"
        if self._last_timestamp_ns is not None and timestamp_ns < self._last_timestamp_ns:
            return "timestamp is older than the last applied transition"
        return None
