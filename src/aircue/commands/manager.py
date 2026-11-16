"""Validate commands against the current state and target capabilities."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from aircue.commands.commands import Command, CommandDecision, CommandRejection
from aircue.commands.priority import highest_priority
from aircue.presentation.target import Capability, TargetCapabilities
from aircue.state.states import InteractionState

S = InteractionState


@dataclass(frozen=True)
class _Gate:
    states: frozenset[InteractionState]
    capability: Capability | None = None


_ALL = frozenset(InteractionState)
_PAUSABLE = frozenset({S.ACTIVE, S.POINTER_MODE, S.SCROLL_MODE})

# A command is available only in the states listed here. Mode exits carry no
# capability requirement so a degraded target can always be left.
_GATES: dict[Command, _Gate] = {
    Command.EXIT: _Gate(_ALL - {S.EXITING}),
    Command.PAUSE: _Gate(_PAUSABLE),
    Command.RESUME: _Gate(frozenset({S.PAUSED})),
    Command.ACTIVATE: _Gate(frozenset({S.IDLE})),
    Command.ENTER_POINTER_MODE: _Gate(
        frozenset({S.ACTIVE}), Capability.POINTER
    ),
    Command.EXIT_POINTER_MODE: _Gate(frozenset({S.POINTER_MODE})),
    Command.ENTER_SCROLL_MODE: _Gate(frozenset({S.ACTIVE}), Capability.POINTER),
    Command.EXIT_SCROLL_MODE: _Gate(frozenset({S.SCROLL_MODE})),
    Command.NEXT_SLIDE: _Gate(frozenset({S.ACTIVE}), Capability.NAVIGATION),
    Command.PREVIOUS_SLIDE: _Gate(frozenset({S.ACTIVE}), Capability.NAVIGATION),
    Command.CLICK: _Gate(frozenset({S.POINTER_MODE}), Capability.POINTER),
    Command.DOUBLE_CLICK: _Gate(frozenset({S.POINTER_MODE}), Capability.POINTER),
    Command.SCROLL: _Gate(frozenset({S.SCROLL_MODE}), Capability.POINTER),
    Command.POINTER_MOVE: _Gate(frozenset({S.POINTER_MODE}), Capability.POINTER),
}


class CommandManager:
    """Gates every command and resolves a batch by priority.

    A command that fails the state or capability gate is recorded as a decision
    with no presentation effect; the highest-priority command is the only one
    considered, so a gated command is never replaced by a lower-priority one.
    """

    def validate(
        self,
        command: Command,
        state: InteractionState,
        capabilities: TargetCapabilities,
    ) -> CommandDecision:
        gate = _GATES[command]
        if state not in gate.states:
            return CommandDecision(
                command=command,
                state=state,
                rejection=CommandRejection.STATE,
                reason=f"{command.value} is not available in {state.value}",
            )
        if gate.capability is not None and not capabilities.supports(gate.capability):
            return CommandDecision(
                command=command,
                state=state,
                rejection=CommandRejection.CAPABILITY,
                reason=(
                    f"{command.value} requires the "
                    f"{gate.capability.value} capability, which the target lacks"
                ),
            )
        return CommandDecision(command=command, state=state)

    def select(
        self,
        commands: Iterable[Command],
        state: InteractionState,
        capabilities: TargetCapabilities,
    ) -> CommandDecision | None:
        command = highest_priority(commands)
        if command is None:
            return None
        return self.validate(command, state, capabilities)
