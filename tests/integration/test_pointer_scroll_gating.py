"""Pointer, click, and scroll output only inside their permitted mode and target."""

from __future__ import annotations

import pytest

from aircue.commands.click import (
    ClickArbiter,
    ClickController,
    ClickDispatch,
    gate_click,
)
from aircue.commands.manager import CommandManager
from aircue.commands.pointer import (
    PointerSmoother,
    check_pointer_movement,
    map_pointer,
)
from aircue.commands.scroll import ScrollController
from aircue.gestures.semantic import GestureAction, SemanticEvent
from aircue.gestures.vocabulary import Gesture
from aircue.presentation.adapter import (
    AdapterResult,
    Click,
    CommandPayload,
    DoubleClick,
    PointerMove,
    Scroll,
)
from aircue.presentation.target import (
    ScreenRect,
    TargetKind,
    capabilities_for,
)
from aircue.state.machine import StateMachine
from aircue.state.states import InteractionState

S = InteractionState
MS = 1_000_000
FULL_HD = ScreenRect(0, 0, 1920, 1080)
SECONDARY = ScreenRect(1920, 0, 3840, 1080)


class RecordingAdapter:
    def __init__(self) -> None:
        self.payloads: list[CommandPayload] = []

    def execute(self, payload: CommandPayload) -> AdapterResult:
        self.payloads.append(payload)
        return AdapterResult()


class Pipeline:
    """The pointer/scroll command path the runtime will compose in task 7.1."""

    def __init__(self, monitor: ScreenRect = FULL_HD) -> None:
        self.manager = CommandManager()
        self.adapter = RecordingAdapter()
        self.smoother = PointerSmoother()
        self.scroll = ScrollController(self.manager)
        self.clicks = ClickArbiter()
        self.monitor = monitor

    def pointer(
        self,
        x: float,
        y: float,
        now_ns: int,
        *,
        state: InteractionState = S.POINTER_MODE,
        kind: TargetKind = TargetKind.NORMAL_SLIDESHOW,
        pinch_closed: bool = False,
    ) -> None:
        decision = check_pointer_movement(
            self.manager,
            state,
            capabilities_for(kind),
            pointer_valid=True,
            pinch_closed=pinch_closed,
            click_pending=self.clicks.pending,
        )
        if not decision.allowed:
            return
        smoothed = self.smoother.update((x, y), now_ns)
        mapped = map_pointer(*smoothed, self.monitor) if smoothed is not None else None
        if mapped is not None:
            self.adapter.execute(PointerMove(*mapped))

    def click(
        self,
        dispatch: ClickDispatch,
        *,
        state: InteractionState = S.POINTER_MODE,
        kind: TargetKind = TargetKind.NORMAL_SLIDESHOW,
        foreground: bool = True,
    ) -> None:
        decision = gate_click(
            self.manager,
            dispatch,
            state,
            capabilities_for(kind),
            foreground=foreground,
        )
        if decision.payload is not None:
            self.adapter.execute(decision.payload)

    def scroll_sample(
        self,
        y: float | None,
        now_ns: int,
        *,
        state: InteractionState = S.SCROLL_MODE,
        kind: TargetKind = TargetKind.NORMAL_SLIDESHOW,
        foreground: bool = True,
    ) -> None:
        update = self.scroll.update(
            y,
            now_ns,
            state,
            capabilities_for(kind),
            foreground=foreground,
        )
        if update.notches:
            self.adapter.execute(Scroll(update.notches))


def candidate(timestamp_ms: int) -> SemanticEvent:
    return SemanticEvent(
        action=GestureAction.CLICK_CANDIDATE,
        gesture=Gesture.PINCH_RELEASE,
        onset_ns=timestamp_ms * MS,
        onset_sequence=0,
        timestamp_ns=timestamp_ms * MS,
        confidence=0.9,
    )


def test_pointer_output_traverses_the_identified_monitor() -> None:
    pipeline = Pipeline(SECONDARY)
    pipeline.pointer(0.5, 0.5, 0)
    assert pipeline.adapter.payloads == [PointerMove(2880, 540)]


@pytest.mark.parametrize(
    "state",
    [
        InteractionState.INITIALIZING,
        InteractionState.IDLE,
        InteractionState.ACTIVE,
        InteractionState.PAUSED,
        InteractionState.SCROLL_MODE,
        InteractionState.ERROR,
        InteractionState.EXITING,
    ],
)
def test_pointer_output_never_occurs_outside_pointer_mode(state: InteractionState) -> None:
    pipeline = Pipeline()
    pipeline.pointer(0.9, 0.1, 0, state=state)
    assert pipeline.adapter.payloads == []


@pytest.mark.parametrize(
    "kind",
    [TargetKind.PRESENTER_VIEW, TargetKind.EDIT_MODE, TargetKind.UNKNOWN],
)
def test_pointer_output_never_occurs_without_pointer_capability(kind: TargetKind) -> None:
    pipeline = Pipeline()
    pipeline.pointer(0.9, 0.1, 0, kind=kind)
    assert pipeline.adapter.payloads == []


def test_a_pending_click_or_closed_pinch_blocks_pointer_output() -> None:
    pending = Pipeline()
    pending.clicks.candidate(0)
    pending.pointer(0.9, 0.1, 0)
    assert pending.adapter.payloads == []

    pinched = Pipeline()
    pinched.pointer(0.9, 0.1, 0, pinch_closed=True)
    assert pinched.adapter.payloads == []


def test_a_single_click_reaches_the_adapter_once() -> None:
    pipeline = Pipeline()
    machine = StateMachine(S.POINTER_MODE)
    controller = ClickController(machine)

    controller.on_event(candidate(0))
    update = controller.advance(350 * MS)
    assert update.dispatch is ClickDispatch.SINGLE
    pipeline.click(update.dispatch)

    assert pipeline.adapter.payloads == [Click()]


def test_a_double_click_reaches_the_adapter_once_without_a_single() -> None:
    pipeline = Pipeline()
    machine = StateMachine(S.POINTER_MODE)
    controller = ClickController(machine)

    assert controller.on_event(candidate(0)).dispatch is None
    dispatch = controller.on_event(candidate(100)).dispatch
    assert dispatch is ClickDispatch.DOUBLE
    pipeline.click(dispatch)

    assert pipeline.adapter.payloads == [DoubleClick()]


@pytest.mark.parametrize(
    "state",
    [
        InteractionState.INITIALIZING,
        InteractionState.IDLE,
        InteractionState.ACTIVE,
        InteractionState.PAUSED,
        InteractionState.SCROLL_MODE,
        InteractionState.ERROR,
        InteractionState.EXITING,
    ],
)
def test_click_output_never_occurs_outside_pointer_mode(state: InteractionState) -> None:
    for dispatch in ClickDispatch:
        pipeline = Pipeline()
        pipeline.click(dispatch, state=state)
        assert pipeline.adapter.payloads == []


@pytest.mark.parametrize(
    "kind",
    [TargetKind.PRESENTER_VIEW, TargetKind.EDIT_MODE, TargetKind.UNKNOWN],
)
def test_click_output_never_occurs_without_pointer_capability(kind: TargetKind) -> None:
    for dispatch in ClickDispatch:
        pipeline = Pipeline()
        pipeline.click(dispatch, kind=kind)
        assert pipeline.adapter.payloads == []


def test_click_output_never_occurs_without_foreground_focus() -> None:
    for dispatch in ClickDispatch:
        pipeline = Pipeline()
        pipeline.click(dispatch, foreground=False)
        assert pipeline.adapter.payloads == []


def test_scroll_emits_nothing_on_entry_and_only_after_movement() -> None:
    pipeline = Pipeline()
    pipeline.scroll_sample(0.2, 0)
    assert pipeline.adapter.payloads == []

    for frame in range(1, 12):
        pipeline.scroll_sample(0.2, frame * 100 * MS)
    assert pipeline.adapter.payloads
    assert all(
        isinstance(payload, Scroll) and payload.notches > 0
        for payload in pipeline.adapter.payloads
    )


@pytest.mark.parametrize(
    "state",
    [
        InteractionState.INITIALIZING,
        InteractionState.IDLE,
        InteractionState.ACTIVE,
        InteractionState.PAUSED,
        InteractionState.POINTER_MODE,
        InteractionState.ERROR,
        InteractionState.EXITING,
    ],
)
def test_scroll_output_never_occurs_outside_scroll_mode(state: InteractionState) -> None:
    pipeline = Pipeline()
    for frame in range(20):
        pipeline.scroll_sample(0.0, frame * 100 * MS, state=state)
    assert pipeline.adapter.payloads == []


@pytest.mark.parametrize(
    "kind",
    [TargetKind.PRESENTER_VIEW, TargetKind.EDIT_MODE, TargetKind.UNKNOWN],
)
def test_scroll_output_never_occurs_without_scroll_capability(kind: TargetKind) -> None:
    pipeline = Pipeline()
    for frame in range(20):
        pipeline.scroll_sample(0.0, frame * 100 * MS, kind=kind)
    assert pipeline.adapter.payloads == []


def test_scroll_stops_on_neutral_loss_of_hand_and_focus() -> None:
    neutral = Pipeline()
    for frame in range(11):
        neutral.scroll_sample(0.0, frame * 100 * MS)
    before_neutral = len(neutral.adapter.payloads)
    assert before_neutral > 0
    for frame in range(11, 16):
        neutral.scroll_sample(0.5, frame * 100 * MS)
    assert len(neutral.adapter.payloads) == before_neutral

    lost = Pipeline()
    for frame in range(5):
        lost.scroll_sample(0.0, frame * 100 * MS)
    before_loss = len(lost.adapter.payloads)
    lost.scroll_sample(None, 500 * MS)
    assert len(lost.adapter.payloads) == before_loss
    lost.scroll_sample(0.0, 600 * MS)
    assert len(lost.adapter.payloads) == before_loss

    unfocused = Pipeline()
    for frame in range(20):
        unfocused.scroll_sample(0.0, frame * 100 * MS, foreground=False)
    assert unfocused.adapter.payloads == []


def test_no_output_at_all_in_active_mode() -> None:
    pipeline = Pipeline()
    pipeline.pointer(0.9, 0.1, 0, state=S.ACTIVE)
    pipeline.click(ClickDispatch.SINGLE, state=S.ACTIVE)
    pipeline.click(ClickDispatch.DOUBLE, state=S.ACTIVE)
    for frame in range(20):
        pipeline.scroll_sample(0.0, frame * 100 * MS, state=S.ACTIVE)
    assert pipeline.adapter.payloads == []
