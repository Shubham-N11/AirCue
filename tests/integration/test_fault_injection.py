"""Fault-injection matrix: every fault stops output and lands on D3.1."""

from __future__ import annotations

import logging
import math
import time
from dataclasses import replace

import numpy as np
import pytest

from aircue.app.runtime import AirCueRuntime
from aircue.capture.mailbox import CaptureThread
from aircue.capture.types import (
    CaptureFailureError,
    CaptureOpenResult,
    CaptureUnavailableError,
    Frame,
)
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
    FakeAdapter,
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


class ReconnectSource(FakeSource):
    """A fake camera that stops producing frames until it is reopened."""

    def __init__(self) -> None:
        super().__init__()
        self.down = False
        self.reopen_ok = True
        self.opens = 0
        self.sequence = 0

    def open(self, mode) -> CaptureOpenResult:
        self.opens += 1
        if self.opens > 1 and not self.reopen_ok:
            raise CaptureUnavailableError("camera is still unavailable")
        self.down = False
        return super().open(mode)

    def read(self) -> Frame:
        if self.down:
            time.sleep(0.005)
            raise CaptureFailureError("camera lost")
        self.sequence += 1
        return Frame(
            np.zeros((2, 2, 3), np.uint8), time.monotonic_ns(), self.sequence
        )


def start_camera_session(
    source: ReconnectSource,
) -> tuple[AirCueRuntime, FakeAdapter, Clock, CaptureThread]:
    config = replace(
        Config(),
        camera=replace(
            Config().camera, reconnect_attempts=3, reconnect_backoff_ms=0
        ),
    )
    clock = Clock()
    adapter = FakeAdapter()
    runtime = AirCueRuntime(
        config,
        source=source,
        tracker=FakeTracker(),
        adapter=adapter,
        clock_ns=clock,
        key_down=lambda _key: False,
    )
    assert runtime.initialize().accepted is True
    capture = CaptureThread(
        source, runtime.frames, on_error=runtime._record_capture_error
    )
    runtime._capture = capture
    capture.start()
    wait_for(lambda: capture.frames_captured > 0, "the first captured frame")
    activate(runtime, 100)
    return runtime, adapter, clock, capture


def lose_camera(runtime: AirCueRuntime, clock: Clock) -> None:
    runtime.tick(200_000_000)
    runtime.tick(2_200_000_000)
    assert runtime.state is S.ACTIVE
    runtime.tick(2_200_000_001)
    assert runtime.state is S.ERROR
    clock.now = 2_200_000_001


def pump_until(runtime: AirCueRuntime, clock: Clock, predicate, timeout: float = 2.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        clock.now += 10_000_000
        runtime.tick()
        if predicate():
            return
        time.sleep(0.002)
    raise AssertionError("timed out pumping the runtime")


def test_a_camera_freeze_reconnects_and_returns_to_idle(
    caplog: pytest.LogCaptureFixture,
) -> None:
    source = ReconnectSource()
    runtime, adapter, clock, _capture = start_camera_session(source)
    try:
        source.down = True
        time.sleep(0.02)
        lose_camera(runtime, clock)

        with caplog.at_level(logging.INFO, logger="aircue.session"):
            pump_until(runtime, clock, lambda: runtime.state is S.IDLE)

        assert runtime.state is S.IDLE
        assert runtime.recovery.error_cause is None
        assert source.opens == 2
        assert any(
            getattr(record, "fields", {}).get("reason")
            == "camera reconnect succeeded"
            for record in caplog.records
        )

        runtime.handle_event(
            event(GestureAction.NEXT_SLIDE, 4_000, Gesture.OPEN_PALM_CLOCKWISE)
        )
        runtime.tick(4_000_000_000)
        assert runtime.state is S.IDLE
        assert adapter.executed == []
    finally:
        runtime.close()


def test_exhausted_camera_reconnects_leave_error_and_exit_works(
    caplog: pytest.LogCaptureFixture,
) -> None:
    source = ReconnectSource()
    source.reopen_ok = False
    runtime, _adapter, clock, _capture = start_camera_session(source)
    try:
        source.down = True
        time.sleep(0.02)
        lose_camera(runtime, clock)

        with caplog.at_level(logging.WARNING, logger="aircue.session"):
            wait_for(
                lambda: runtime.recovery.reconnect_attempts_left == 0,
                "three failed reconnect attempts",
            )

        assert runtime.state is S.ERROR
        attempts = [
            getattr(record, "fields", {})
            for record in caplog.records
            if getattr(record, "fields", {}).get("reason")
            == "camera reconnect attempt failed"
        ]
        assert [fields["attempt"] for fields in attempts] == [1, 2, 3]
        assert [fields["attempts_left"] for fields in attempts] == [2, 1, 0]
        assert source.opens == 4

        record = runtime.request_exit()
        assert record.accepted is True
        assert runtime.state is S.EXITING
        runtime.shutdown()
        assert runtime.machine.terminated is True
    finally:
        runtime.close()


def test_camera_loss_enters_error_and_stops_output() -> None:
    config = replace(
        Config(),
        camera=replace(Config().camera, reconnect_attempts=0),
    )
    with session(config=config) as (runtime, adapter, _clock, _tracker):
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
