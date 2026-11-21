"""Fault-injection matrix: every fault stops output and lands on D3.1."""

from __future__ import annotations

import math
from dataclasses import replace

import pytest

from aircue.app.runtime import AirCueRuntime
from aircue.config.schema import Config
from aircue.gestures.semantic import GestureAction
from aircue.gestures.vocabulary import Gesture
from aircue.presentation.adapter import AdapterError, Navigate, SlideDirection
from aircue.presentation.target import TargetKind
from aircue.state.states import InteractionState
from aircue.state.transitions import TransitionTrigger
from tests.fixtures.landmarks import make_observation
from tests.integration.test_runtime_session import (
    BlockingAdapter,
    Clock,
    FakeSource,
    FakeTracker,
    activate,
    event,
    fist_observation,
    frame,
    session,
    wait_for,
)

S = InteractionState


class FrozenCapture:
    """A capture thread whose frame count never advances."""

    def __init__(self) -> None:
        self.frames_captured = 0

    def stop(self) -> bool:
        return True


def test_camera_loss_enters_error_and_stops_output() -> None:
    with session() as (runtime, adapter, _clock, _tracker):
        activate(runtime, 100)
        # The runtime's camera watchdog is the fault injector; no real camera
        # is opened, so stand in for the capture thread's frame counter.
        runtime._capture = FrozenCapture()

        runtime.tick(200_000_000)
        runtime.tick(2_200_000_000)
        assert runtime.state is S.ACTIVE

        runtime.tick(2_200_000_001)

        assert runtime.state is S.ERROR
        assert runtime.recovery.error_cause is TransitionTrigger.CAMERA_FAULT
        assert (
            runtime.recovery.reconnect_attempts_left
            == runtime.config.camera.reconnect_attempts
        )

        runtime.handle_event(
            event(GestureAction.NEXT_SLIDE, 2_300, Gesture.OPEN_PALM_CLOCKWISE)
        )
        runtime.tick(2_300_000_000)
        assert adapter.executed == []


@pytest.mark.parametrize(
    "landmark",
    [
        (math.nan, 0.30, 0.0, 0.9),
        (math.inf, 0.30, 0.0, 0.9),
        (1.20, 0.30, 0.0, 0.9),
        (0.45, -0.10, 0.0, 0.9),
    ],
)
def test_an_invalid_landmark_frame_is_discarded_without_output(
    landmark: tuple[float, float, float, float],
) -> None:
    with session() as (runtime, adapter, _clock, tracker):
        activate(runtime, 100)
        tracker.observations = (make_observation({8: landmark}),)

        assert runtime.process_frame(frame(200, 1)) is None
        runtime.tick(200_000_000)

        assert runtime.state is S.ACTIVE
        assert runtime._invalid_frames == 1
        assert adapter.executed == []


def test_a_low_confidence_hand_cannot_trigger_a_gesture() -> None:
    with session() as (runtime, adapter, _clock, tracker):
        activate(runtime, 100)
        fist = fist_observation()
        tracker.observations = (
            replace(
                fist,
                confidence=0.1,
                landmarks=tuple(
                    replace(landmark, confidence=0.1)
                    for landmark in fist.landmarks
                ),
            ),
        )

        for index, milliseconds in enumerate((200, 400, 600), start=1):
            assert runtime.process_frame(frame(milliseconds, index)) is None
            runtime.tick(milliseconds * 1_000_000)

        assert runtime.state is S.ACTIVE
        assert adapter.executed == []


def test_a_partially_occluded_hand_cannot_trigger_a_gesture() -> None:
    with session() as (runtime, adapter, _clock, tracker):
        activate(runtime, 100)
        fist = fist_observation()
        tracker.observations = (replace(fist, landmarks=fist.landmarks[:18]),)

        for index, milliseconds in enumerate((200, 400, 600), start=1):
            assert runtime.process_frame(frame(milliseconds, index)) is None
            runtime.tick(milliseconds * 1_000_000)

        assert runtime.state is S.ACTIVE
        assert adapter.executed == []


def test_focus_loss_pauses_and_requires_deliberate_resume() -> None:
    with session() as (runtime, adapter, _clock, _tracker):
        activate(runtime, 100)

        adapter.kind = TargetKind.UNKNOWN
        runtime.tick(200_000_000)

        assert runtime.state is S.PAUSED
        assert adapter.executed == []

        adapter.kind = TargetKind.NORMAL_SLIDESHOW
        runtime.tick(300_000_000)
        assert runtime.state is S.PAUSED

        runtime.handle_event(
            event(GestureAction.NEXT_SLIDE, 400, Gesture.OPEN_PALM_CLOCKWISE)
        )
        runtime.tick(400_000_000)
        assert adapter.executed == []


def test_an_unrecoverable_adapter_failure_enters_error_and_is_not_retried() -> None:
    with session() as (runtime, adapter, _clock, _tracker):
        activate(runtime, 100)
        adapter.error = AdapterError.INPUT_BLOCKED
        runtime.handle_event(
            event(GestureAction.NEXT_SLIDE, 200, Gesture.OPEN_PALM_CLOCKWISE)
        )

        assert runtime.worker is not None
        wait_for(
            lambda: runtime.worker is not None and runtime.worker.stats().errors >= 1,
            "the adapter error outcome",
        )
        runtime.tick(300_000_000)

        assert runtime.state is S.ERROR
        assert adapter.executed == [Navigate(SlideDirection.NEXT)]

        adapter.error = None
        runtime.handle_event(
            event(GestureAction.PREV_SLIDE, 400, Gesture.OPEN_PALM_COUNTERCLOCKWISE)
        )
        runtime.tick(400_000_000)
        assert adapter.executed == [Navigate(SlideDirection.NEXT)]


def test_an_unresponsive_adapter_enters_error_at_the_threshold() -> None:
    clock = Clock()
    adapter = BlockingAdapter()
    runtime = AirCueRuntime(
        Config(),
        source=FakeSource(),
        tracker=FakeTracker(),
        adapter=adapter,
        clock_ns=clock,
        key_down=lambda _key: False,
    )
    assert runtime.initialize().accepted is True
    assert runtime.worker is not None
    runtime.worker.start()
    try:
        activate(runtime, 100)
        clock.now = 200_000_000
        runtime.handle_event(
            event(GestureAction.NEXT_SLIDE, 200, Gesture.OPEN_PALM_CLOCKWISE)
        )
        assert adapter.started.wait(2.0)

        runtime.tick(500_000_000)
        assert runtime.state is S.ACTIVE

        runtime.tick(501_000_000)

        assert runtime.state is S.ERROR
        assert adapter.executed == [Navigate(SlideDirection.NEXT)]

        assert (
            runtime.handle_event(
                event(GestureAction.PREV_SLIDE, 600, Gesture.OPEN_PALM_COUNTERCLOCKWISE)
            )
            is None
        )
        runtime.tick(600_000_000)
        assert adapter.executed == [Navigate(SlideDirection.NEXT)]
    finally:
        adapter.gate.set()
        runtime.close()


def test_powerpoint_exit_pauses_and_sends_no_further_input() -> None:
    with session() as (runtime, adapter, _clock, _tracker):
        activate(runtime, 100)
        adapter.error = AdapterError.TARGET_UNAVAILABLE
        runtime.handle_event(
            event(GestureAction.NEXT_SLIDE, 200, Gesture.OPEN_PALM_CLOCKWISE)
        )

        assert runtime.worker is not None
        wait_for(
            lambda: runtime.worker is not None and runtime.worker.stats().errors >= 1,
            "the target-unavailable outcome",
        )
        runtime.tick(300_000_000)

        assert runtime.state is S.PAUSED
        assert adapter.executed == [Navigate(SlideDirection.NEXT)]

        runtime.handle_event(
            event(GestureAction.NEXT_SLIDE, 400, Gesture.OPEN_PALM_CLOCKWISE)
        )
        runtime.tick(400_000_000)
        assert adapter.executed == [Navigate(SlideDirection.NEXT)]


def test_a_rejected_command_sends_no_input_and_keeps_the_state() -> None:
    with session() as (runtime, adapter, _clock, _tracker):
        runtime.handle_event(
            event(GestureAction.NEXT_SLIDE, 100, Gesture.OPEN_PALM_CLOCKWISE)
        )
        runtime.tick(100_000_000)

        assert runtime.state is S.IDLE
        assert adapter.executed == []
