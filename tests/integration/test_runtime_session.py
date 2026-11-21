"""The four-thread runtime: states, modes, and every command end to end."""

from __future__ import annotations

import json
import logging
import math
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager

import numpy as np
import pytest

from aircue.app.hotkeys import VK_CONTROL, VK_MENU
from aircue.app.runtime import AirCueRuntime
from aircue.capture.types import CaptureOpenResult, Frame
from aircue.config.schema import Config
from aircue.diagnostics.session_log import close_session_logging, configure_session_logging
from aircue.gestures.semantic import GestureAction, SemanticEvent
from aircue.gestures.vocabulary import Gesture
from aircue.performance.timing import FrameTimings, Stage
from aircue.presentation.adapter import (
    AdapterError,
    AdapterResult,
    Click,
    CommandPayload,
    DoubleClick,
    Navigate,
    PointerMove,
    Scroll,
    SlideDirection,
)
from aircue.presentation.target import (
    ScreenRect,
    TargetKind,
    TargetSnapshot,
    capabilities_for,
)
from aircue.state.states import InteractionState
from aircue.vision.types import (
    INDEX_MCP,
    INDEX_PIP,
    INDEX_TIP,
    MIDDLE_MCP,
    MIDDLE_PIP,
    MIDDLE_TIP,
    PINKY_PIP,
    PINKY_TIP,
    RING_PIP,
    RING_TIP,
    THUMB_IP,
    THUMB_MCP,
    THUMB_TIP,
    HandObservation,
)
from tests.fixtures.landmarks import BASE_POSE, make_landmarks

S = InteractionState
MS = 1_000_000
MONITOR = ScreenRect(0, 0, 1920, 1080)


def at(clock: Clock, milliseconds: int) -> int:
    clock.now = milliseconds * MS
    return clock.now


class Clock:
    def __init__(self) -> None:
        self.now = 0

    def __call__(self) -> int:
        return self.now


class FakeSource:
    def __init__(self) -> None:
        self.mode = None
        self.closed = False

    def open(self, mode):
        self.mode = mode
        return CaptureOpenResult(mode, mode, ())

    def read(self) -> Frame:
        raise AssertionError("the fake source is not read in this test")

    def close(self) -> None:
        self.closed = True
        self.mode = None


class SpinningSource(FakeSource):
    """A source the capture thread can run against without a camera."""

    def __init__(self) -> None:
        super().__init__()
        self.sequence = 0

    def read(self) -> Frame:
        time.sleep(0.002)
        self.sequence += 1
        return Frame(np.zeros((2, 2, 3), np.uint8), time.monotonic_ns(), self.sequence)


class FakeTracker:
    def __init__(self, observations: tuple[HandObservation, ...] = ()) -> None:
        self.observations = observations
        self.detects = 0
        self.closed = False

    def detect(self, frame: Frame) -> tuple[HandObservation, ...]:
        self.detects += 1
        return self.observations

    def close(self) -> None:
        self.closed = True


class FakeAdapter:
    def __init__(self, kind: TargetKind = TargetKind.NORMAL_SLIDESHOW) -> None:
        self.kind = kind
        self.executed: list[CommandPayload] = []
        self.error: AdapterError | None = None

    def snapshot(self) -> TargetSnapshot:
        return TargetSnapshot(
            captured_ns=0,
            kind=self.kind,
            capabilities=capabilities_for(self.kind),
            monitor_bounds=MONITOR,
        )

    def refresh(self) -> TargetSnapshot:
        return self.snapshot()

    def execute(self, payload: CommandPayload) -> AdapterResult:
        self.executed.append(payload)
        return AdapterResult(self.error)


@contextmanager
def session(
    kind: TargetKind = TargetKind.NORMAL_SLIDESHOW,
    observations: tuple[HandObservation, ...] = (),
    keys: set[int] | None = None,
    config: Config | None = None,
) -> Iterator[tuple[AirCueRuntime, FakeAdapter, Clock, FakeTracker]]:
    clock = Clock()
    adapter = FakeAdapter(kind)
    tracker = FakeTracker(observations)
    down = keys if keys is not None else set()
    runtime = AirCueRuntime(
        config or Config(),
        source=FakeSource(),
        tracker=tracker,
        adapter=adapter,
        clock_ns=clock,
        key_down=down.__contains__,
    )
    assert runtime.initialize().accepted is True
    assert runtime.worker is not None
    runtime.worker.start()
    try:
        yield runtime, adapter, clock, tracker
    finally:
        runtime.close()


def event(action: GestureAction, milliseconds: int, gesture: Gesture) -> SemanticEvent:
    timestamp = milliseconds * MS
    return SemanticEvent(
        action=action,
        gesture=gesture,
        onset_ns=timestamp,
        onset_sequence=0,
        timestamp_ns=timestamp,
        confidence=0.9,
    )


def event_with_onset(
    action: GestureAction,
    onset_ms: int,
    timestamp_ms: int,
    gesture: Gesture,
) -> SemanticEvent:
    return SemanticEvent(
        action=action,
        gesture=gesture,
        onset_ns=onset_ms * MS,
        onset_sequence=0,
        timestamp_ns=timestamp_ms * MS,
        confidence=0.9,
    )


def activate(runtime: AirCueRuntime, milliseconds: int) -> None:
    record = runtime.handle_event(
        event(GestureAction.ACTIVATE, milliseconds, Gesture.THUMBS_UP)
    )
    assert record is not None and record.accepted is True


def wait_for(predicate, description: str, timeout: float = 2.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.002)
    raise AssertionError(f"timed out waiting for {description}")


def test_initializing_reaches_idle_and_a_confirmed_thumbs_up_activates() -> None:
    with session() as (runtime, _adapter, _clock, _tracker):
        assert runtime.state is S.IDLE

        record = runtime.handle_event(
            event(GestureAction.ACTIVATE, 100, Gesture.THUMBS_UP)
        )

        assert record is not None and record.accepted is True
        assert runtime.state is S.ACTIVE
        assert runtime.feedback.status.state is S.ACTIVE


def test_activation_hotkey_works_while_a_slideshow_is_foreground() -> None:
    keys = {VK_CONTROL, VK_MENU}
    with session(keys=keys) as (runtime, _adapter, clock, _tracker):
        keys.add(ord("A"))
        runtime.tick(at(clock, 100))

        assert runtime.state is S.ACTIVE
        generation = runtime.machine.generation

        runtime.tick(at(clock, 200))
        assert runtime.state is S.ACTIVE
        assert runtime.machine.generation == generation


def test_deactivation_hotkey_leaves_pointer_mode_for_idle() -> None:
    keys = {VK_CONTROL, VK_MENU}
    with session(keys=keys) as (runtime, adapter, clock, _tracker):
        activate(runtime, 100)
        runtime.handle_event(
            event(GestureAction.ENTER_POINTER_MODE, 200, Gesture.PINCH)
        )
        assert runtime.state is S.POINTER_MODE

        keys.add(ord("D"))
        runtime.tick(at(clock, 300))

        assert runtime.state is S.IDLE
        assert adapter.executed == []


def test_exit_hotkey_works_from_paused_and_records_its_effect(
    caplog: pytest.LogCaptureFixture,
) -> None:
    keys = {VK_CONTROL, VK_MENU}
    with session(keys=keys) as (runtime, _adapter, clock, _tracker):
        activate(runtime, 100)
        runtime.handle_event(event(GestureAction.PAUSE_TRACKING, 200, Gesture.FIST))
        assert runtime.state is S.PAUSED

        keys.add(ord("Q"))
        with caplog.at_level(logging.INFO, logger="aircue.runtime"):
            runtime.tick(at(clock, 300))

        assert runtime.state is S.EXITING
        assert any(
            "ctrl+alt+q" in message and "exiting" in message
            for message in caplog.messages
        )

        runtime.shutdown()
        assert runtime.machine.terminated is True


def test_activation_hotkey_outside_idle_has_no_effect_and_is_logged(
    caplog: pytest.LogCaptureFixture,
) -> None:
    keys = {VK_CONTROL, VK_MENU, ord("A")}
    with session(keys=keys) as (runtime, _adapter, clock, _tracker):
        activate(runtime, 100)
        generation = runtime.machine.generation

        with caplog.at_level(logging.INFO, logger="aircue.runtime"):
            runtime.tick(at(clock, 200))

        assert runtime.state is S.ACTIVE
        assert runtime.machine.generation == generation
        assert any(
            "ctrl+alt+a" in message and "no effect" in message
            for message in caplog.messages
        )


def test_activation_without_a_slideshow_target_is_rejected() -> None:
    for kind in (TargetKind.EDIT_MODE, TargetKind.UNKNOWN):
        with session(kind=kind) as (runtime, _adapter, _clock, _tracker):
            assert (
                runtime.handle_event(
                    event(GestureAction.ACTIVATE, 100, Gesture.THUMBS_UP)
                )
                is None
            )
            assert runtime.state is S.IDLE


def test_presenter_view_navigates_but_rejects_pointer_and_scroll_modes() -> None:
    with session(kind=TargetKind.PRESENTER_VIEW) as (runtime, adapter, _clock, _t):
        activate(runtime, 100)
        assert runtime.state is S.ACTIVE

        runtime.handle_event(
            event(GestureAction.NEXT_SLIDE, 200, Gesture.OPEN_PALM_CLOCKWISE)
        )
        wait_for(
            lambda: adapter.executed == [Navigate(SlideDirection.NEXT)],
            "PresenterView navigation",
        )

        assert (
            runtime.handle_event(
                event(GestureAction.ENTER_POINTER_MODE, 300, Gesture.PINCH)
            )
            is None
        )
        assert (
            runtime.handle_event(
                event(GestureAction.ENTER_SCROLL_MODE, 400, Gesture.PEACE)
            )
            is None
        )
        assert runtime.state is S.ACTIVE


def test_both_rotation_directions_reach_the_adapter() -> None:
    with session() as (runtime, adapter, _clock, _tracker):
        activate(runtime, 100)
        runtime.handle_event(
            event(GestureAction.NEXT_SLIDE, 200, Gesture.OPEN_PALM_CLOCKWISE)
        )
        runtime.handle_event(
            event(GestureAction.PREV_SLIDE, 300, Gesture.OPEN_PALM_COUNTERCLOCKWISE)
        )

        wait_for(
            lambda: adapter.executed
            == [Navigate(SlideDirection.NEXT), Navigate(SlideDirection.PREVIOUS)],
            "navigation in both directions",
        )


def curled_tip(mcp: int, pip: int, length: float = 0.08) -> tuple[float, float, float, float]:
    mcp_x, mcp_y, _ = BASE_POSE[mcp]
    pip_x, pip_y, _ = BASE_POSE[pip]
    dx, dy = mcp_x - pip_x, mcp_y - pip_y
    norm = math.hypot(dx, dy)
    return (pip_x + dx / norm * length, pip_y + dy / norm * length, 0.0, 0.9)


def pointer_observation(
    x: float = 0.45, y: float = 0.30, *, confidence: float = 0.9
) -> HandObservation:
    mcp_x, mcp_y, _ = BASE_POSE[INDEX_MCP]
    dx, dy = x - mcp_x, y - mcp_y
    index_pip = (mcp_x + 0.3 * dx, mcp_y + 0.3 * dy, 0.0, confidence)
    overrides = {
        THUMB_IP: (0.40, 0.55, 0.0, confidence),
        THUMB_TIP: (0.4727, 0.4227, 0.0, confidence),
        INDEX_PIP: index_pip,
        INDEX_TIP: (x, y, 0.0, confidence),
        MIDDLE_TIP: curled_tip(MIDDLE_MCP, MIDDLE_PIP),
        RING_TIP: curled_tip(13, RING_PIP),
        PINKY_TIP: curled_tip(17, PINKY_PIP),
    }
    return HandObservation(
        track_id=0,
        landmarks=make_landmarks(overrides, confidence=confidence),
        confidence=confidence,
        handedness="Right",
    )


def fist_observation() -> HandObservation:
    from tests.integration.test_gesture_pipeline import curled_tip, pose_overrides

    overrides = pose_overrides(curled=("index", "middle", "ring", "pinky"))
    overrides[THUMB_TIP] = curled_tip(THUMB_MCP, THUMB_IP)
    return HandObservation(
        track_id=0,
        landmarks=make_landmarks(overrides, confidence=0.9),
        confidence=0.9,
        handedness="Right",
    )


def frame(
    milliseconds: int, sequence: int, timings: FrameTimings | None = None
) -> Frame:
    return Frame(
        np.zeros((2, 2, 3), np.uint8), milliseconds * MS, sequence, timings
    )


def test_pointer_mode_moves_the_cursor_on_the_identified_monitor() -> None:
    with session() as (runtime, adapter, clock, tracker):
        activate(runtime, 100)
        runtime.handle_event(
            event(GestureAction.ENTER_POINTER_MODE, 200, Gesture.PINCH)
        )
        assert runtime.state is S.POINTER_MODE

        tracker.observations = (pointer_observation(0.5, 0.3),)
        runtime.process_frame(frame(300, 1))
        runtime.tick(at(clock, 300))

        wait_for(
            lambda: adapter.executed == [PointerMove(960, 0)],
            "one pointer move on the slideshow monitor",
        )


def test_single_click_waits_for_the_double_click_window() -> None:
    with session() as (runtime, adapter, clock, _tracker):
        activate(runtime, 100)
        runtime.handle_event(
            event(GestureAction.ENTER_POINTER_MODE, 200, Gesture.PINCH)
        )
        runtime.handle_event(
            event(GestureAction.CLICK_CANDIDATE, 300, Gesture.PINCH_RELEASE)
        )

        runtime.tick(at(clock, 600))
        assert adapter.executed == []

        runtime.tick(at(clock, 651))
        wait_for(lambda: adapter.executed == [Click()], "the pending single click")


def test_a_second_candidate_dispatches_one_double_click() -> None:
    with session() as (runtime, adapter, clock, _tracker):
        activate(runtime, 100)
        runtime.handle_event(
            event(GestureAction.ENTER_POINTER_MODE, 200, Gesture.PINCH)
        )
        runtime.handle_event(
            event(GestureAction.CLICK_CANDIDATE, 300, Gesture.PINCH_RELEASE)
        )
        runtime.handle_event(
            event(GestureAction.CLICK_CANDIDATE, 400, Gesture.PINCH_RELEASE)
        )

        wait_for(lambda: adapter.executed == [DoubleClick()], "one double click")

        runtime.tick(at(clock, 1_000))
        assert adapter.executed == [DoubleClick()]


def test_long_pinch_exits_pointer_mode_and_cancels_the_pending_click() -> None:
    with session() as (runtime, adapter, clock, _tracker):
        activate(runtime, 100)
        runtime.handle_event(
            event(GestureAction.ENTER_POINTER_MODE, 200, Gesture.PINCH)
        )
        runtime.handle_event(
            event(GestureAction.CLICK_CANDIDATE, 300, Gesture.PINCH_RELEASE)
        )

        record = runtime.handle_event(
            event(GestureAction.EXIT_POINTER_MODE, 400, Gesture.PINCH)
        )

        assert record is not None and record.accepted is True
        assert runtime.state is S.ACTIVE
        runtime.tick(at(clock, 1_000))
        assert adapter.executed == []


def test_scroll_mode_emits_notches_only_after_deliberate_movement() -> None:
    with session() as (runtime, adapter, clock, tracker):
        activate(runtime, 100)
        runtime.handle_event(
            event(GestureAction.ENTER_SCROLL_MODE, 200, Gesture.PEACE)
        )
        assert runtime.state is S.SCROLL_MODE

        tracker.observations = (pointer_observation(0.45, 0.2),)
        for index in range(13):
            timestamp = 300 + index * 100
            runtime.process_frame(frame(timestamp, index + 1))
            runtime.tick(at(clock, timestamp))

        wait_for(
            lambda: any(
                isinstance(payload, Scroll) and payload.notches > 0
                for payload in adapter.executed
            ),
            "upward scroll notches",
        )
        assert all(
            isinstance(payload, Scroll) for payload in adapter.executed
        ), adapter.executed

        record = runtime.handle_event(
            event(GestureAction.EXIT_SCROLL_MODE, 1_600, Gesture.PEACE)
        )
        assert record is not None and record.accepted is True
        assert runtime.state is S.ACTIVE


def test_exit_from_active_reaches_terminated() -> None:
    with session() as (runtime, _adapter, clock, _tracker):
        activate(runtime, 100)

        record = runtime.handle_event(
            event(GestureAction.EXIT_REQUEST, 200, Gesture.SHAKA)
        )
        assert record is not None and record.accepted is True
        assert runtime.state is S.EXITING

        at(clock, 200)
        runtime.shutdown()
        assert runtime.machine.terminated is True


def test_pause_cancels_a_pending_click_and_resume_returns_to_active() -> None:
    with session() as (runtime, adapter, clock, _tracker):
        activate(runtime, 100)
        runtime.handle_event(
            event(GestureAction.ENTER_POINTER_MODE, 200, Gesture.PINCH)
        )
        runtime.handle_event(
            event(GestureAction.CLICK_CANDIDATE, 300, Gesture.PINCH_RELEASE)
        )

        runtime.handle_event(
            event(GestureAction.PAUSE_TRACKING, 400, Gesture.FIST)
        )
        assert runtime.state is S.PAUSED

        runtime.tick(at(clock, 1_000))
        assert adapter.executed == []

        record = runtime.handle_event(
            event(GestureAction.RESUME_TRACKING, 1_100, Gesture.THUMBS_UP)
        )
        assert record is not None and record.accepted is True
        assert runtime.state is S.ACTIVE


def test_focus_loss_pauses_and_resume_is_still_deliberate() -> None:
    with session() as (runtime, adapter, clock, _tracker):
        activate(runtime, 100)
        runtime.handle_event(
            event(GestureAction.ENTER_POINTER_MODE, 200, Gesture.PINCH)
        )
        runtime.handle_event(
            event(GestureAction.CLICK_CANDIDATE, 300, Gesture.PINCH_RELEASE)
        )

        adapter.kind = TargetKind.UNKNOWN
        runtime.tick(at(clock, 400))
        assert runtime.state is S.PAUSED

        runtime.tick(at(clock, 1_000))
        assert adapter.executed == []

        adapter.kind = TargetKind.NORMAL_SLIDESHOW
        runtime.tick(at(clock, 1_100))
        assert runtime.state is S.PAUSED

        record = runtime.handle_event(
            event(GestureAction.RESUME_TRACKING, 1_200, Gesture.THUMBS_UP)
        )
        assert record is not None and record.accepted is True
        assert runtime.state is S.ACTIVE


def test_tracking_timeout_returns_to_idle() -> None:
    with session() as (runtime, _adapter, clock, tracker):
        activate(runtime, 100)

        tracker.observations = ()
        runtime.process_frame(frame(200, 1))
        runtime.tick(at(clock, 1_300))

        assert runtime.state is S.IDLE


def test_an_adapter_failure_enters_error_and_exit_still_works() -> None:
    with session() as (runtime, adapter, clock, _tracker):
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
        runtime.tick(at(clock, 300))
        assert runtime.state is S.ERROR

        at(clock, 400)
        record = runtime.handle_event(
            event(GestureAction.EXIT_REQUEST, 400, Gesture.SHAKA)
        )
        assert record is not None and record.accepted is True
        assert runtime.state is S.EXITING

        runtime.shutdown()
        assert runtime.machine.terminated is True


def test_the_four_thread_runtime_starts_and_stops_cleanly() -> None:
    source = SpinningSource()
    tracker = FakeTracker()
    adapter = FakeAdapter()
    runtime = AirCueRuntime(
        Config(), source=source, tracker=tracker, adapter=adapter
    )
    assert runtime.initialize().accepted is True
    stop = threading.Event()
    thread = threading.Thread(target=runtime.run, kwargs={"stop": stop}, daemon=True)
    thread.start()
    try:
        wait_for(lambda: tracker.detects > 0, "the vision worker to process a frame")
    finally:
        stop.set()
        thread.join(5.0)

    assert not thread.is_alive()
    assert source.closed is True
    assert tracker.closed is True
    assert runtime.state is S.IDLE


def rotated_observation(angle_deg: float) -> HandObservation:
    from tests.integration.test_gesture_pipeline import pose_overrides, rotate

    return HandObservation(
        track_id=0,
        landmarks=rotate(
            make_landmarks(pose_overrides(), confidence=0.9), angle_deg
        ),
        confidence=0.9,
        handedness="Right",
    )


def test_a_traced_command_shares_a_session_and_ordered_timestamps(tmp_path) -> None:
    log_path = configure_session_logging(tmp_path, session_id="trace-1")
    assert log_path is not None
    try:
        with session() as (runtime, adapter, clock, tracker):
            activate(runtime, 100)
            generation = runtime.machine.generation

            tracker.observations = (rotated_observation(0.0),)
            assert runtime.process_frame(frame(200, 1)) is None
            tracker.observations = (rotated_observation(30.0),)
            assert runtime.process_frame(frame(300, 2)) is not None

            runtime.tick(at(clock, 400))
            wait_for(
                lambda: runtime.worker is not None
                and runtime.worker.stats().delivered == 1,
                "the traced navigation to reach the adapter",
            )
            assert adapter.executed == [Navigate(SlideDirection.NEXT)]
    finally:
        close_session_logging()

    records = [
        json.loads(line)
        for line in log_path.read_text(encoding="utf-8").splitlines()
        if line
    ]
    assert {record["session"] for record in records} == {"trace-1"}

    traced = [
        record
        for record in records
        if record.get("generation") == generation
        and (
            record.get("action") == GestureAction.NEXT_SLIDE.value
            or record.get("command") == "Navigate"
        )
    ]
    assert [record["event"] for record in traced] == [
        "gesture",
        "state",
        "dispatch",
        "adapter",
    ]
    assert [record["ts_ns"] for record in traced] == sorted(
        record["ts_ns"] for record in traced
    )
    assert [record["timestamp_ns"] for record in traced] == sorted(
        record["timestamp_ns"] for record in traced
    )
    assert traced[2]["sequence"] == traced[3]["sequence"]
    assert traced[3]["status"] == "delivered"


@pytest.mark.parametrize(
    "target",
    [
        S.INITIALIZING,
        S.IDLE,
        S.ACTIVE,
        S.PAUSED,
        S.POINTER_MODE,
        S.SCROLL_MODE,
        S.ERROR,
    ],
)
def test_shutdown_terminates_from_every_non_terminated_state(
    target: InteractionState,
) -> None:
    clock = Clock()
    source = FakeSource()
    tracker = FakeTracker()
    adapter = FakeAdapter()
    runtime = AirCueRuntime(
        Config(),
        source=source,
        tracker=tracker,
        adapter=adapter,
        clock_ns=clock,
        key_down=lambda _key: False,
    )
    if target is not S.INITIALIZING:
        assert runtime.initialize().accepted is True
        at(clock, 100)
        if target is not S.IDLE:
            activate(runtime, 100)
        if target is S.PAUSED:
            runtime.handle_event(
                event(GestureAction.PAUSE_TRACKING, 200, Gesture.FIST)
            )
        elif target is S.POINTER_MODE:
            runtime.handle_event(
                event(GestureAction.ENTER_POINTER_MODE, 200, Gesture.PINCH)
            )
        elif target is S.SCROLL_MODE:
            runtime.handle_event(
                event(GestureAction.ENTER_SCROLL_MODE, 200, Gesture.PEACE)
            )
        elif target is S.ERROR:
            assert runtime.worker is not None
            runtime.worker.start()
            adapter.error = AdapterError.INTERNAL
            runtime.handle_event(
                event(GestureAction.NEXT_SLIDE, 200, Gesture.OPEN_PALM_CLOCKWISE)
            )
            wait_for(
                lambda: runtime.worker is not None
                and runtime.worker.stats().errors == 1,
                "the adapter error",
            )
            runtime.tick(at(clock, 300))
        assert runtime.state is target

    at(clock, 400)
    record = runtime.request_exit()
    assert record.accepted is True
    assert runtime.state is S.EXITING

    at(clock, 500)
    runtime.shutdown()

    assert runtime.machine.terminated is True
    assert runtime.worker is None
    assert runtime.source is None
    assert runtime.tracker is None
    if target is not S.INITIALIZING:
        assert source.closed is True
        assert tracker.closed is True


class BlockingAdapter(FakeAdapter):
    def __init__(self) -> None:
        super().__init__()
        self.started = threading.Event()
        self.gate = threading.Event()

    def execute(self, payload: CommandPayload) -> AdapterResult:
        self.executed.append(payload)
        self.started.set()
        self.gate.wait(5.0)
        return AdapterResult(self.error)


def test_a_wedged_command_worker_is_abandoned_and_shutdown_completes(
    caplog: pytest.LogCaptureFixture,
) -> None:
    clock = Clock()
    source = FakeSource()
    tracker = FakeTracker()
    adapter = BlockingAdapter()
    runtime = AirCueRuntime(
        Config(),
        source=source,
        tracker=tracker,
        adapter=adapter,
        clock_ns=clock,
        key_down=lambda _key: False,
    )
    assert runtime.initialize().accepted is True
    worker = runtime.worker
    assert worker is not None
    worker.start()
    try:
        activate(runtime, 100)
        runtime.handle_event(
            event(GestureAction.NEXT_SLIDE, 200, Gesture.OPEN_PALM_CLOCKWISE)
        )
        assert adapter.started.wait(2.0)

        at(clock, 300)
        assert runtime.request_exit().accepted is True
        at(clock, 400)
        with caplog.at_level(logging.ERROR, logger="aircue.session"):
            started_at = time.monotonic()
            runtime.shutdown()
            elapsed = time.monotonic() - started_at

        assert elapsed < 2.0
        assert runtime.machine.terminated is True
        assert source.closed is True
        assert tracker.closed is True
        assert worker._thread is not None and worker._thread.daemon is True
        assert any(
            getattr(record, "fields", {}).get("reason")
            == "command worker did not stop"
            for record in caplog.records
        )
    finally:
        adapter.gate.set()
        runtime.close()


def test_state_action_metrics_end_at_the_accepted_transition() -> None:
    with session() as (runtime, _adapter, clock, tracker):
        activate(runtime, 100)
        tracker.observations = (fist_observation(),)
        runtime.process_frame(frame(200, 1, FrameTimings()))
        confirmed = runtime.process_frame(frame(400, 2, FrameTimings()))
        assert confirmed is not None

        runtime.tick(at(clock, 450))

        assert runtime.state is S.PAUSED
        assert runtime.metrics.values("pause_tracking.pipeline") == (200 * MS,)
        assert runtime.metrics.values("pause_tracking.gesture_response") == (200 * MS,)
        assert runtime.metrics.values("pause_tracking.capture_to_action") == (0,)


def test_single_click_metrics_include_confirmation_and_pending_window() -> None:
    with session() as (runtime, adapter, clock, _tracker):
        activate(runtime, 100)
        runtime.handle_event(
            event(GestureAction.ENTER_POINTER_MODE, 200, Gesture.PINCH)
        )
        runtime.handle_event(
            event_with_onset(
                GestureAction.CLICK_CANDIDATE, 200, 300, Gesture.PINCH_RELEASE
            ),
            timings=FrameTimings(capture_ts_ns=300 * MS),
        )

        runtime.tick(at(clock, 650))
        wait_for(lambda: adapter.executed == [Click()], "the pending single click")
        runtime.tick(at(clock, 650))

        assert runtime.metrics.values("click.pipeline") == (450 * MS,)
        assert runtime.metrics.values("click.gesture_response") == (450 * MS,)
        assert runtime.metrics.values("click.capture_to_action") == (350 * MS,)
        assert runtime.metrics.values("click.dispatch") == (0,)


def test_exit_metrics_include_the_hold_and_end_entering_exiting() -> None:
    with session() as (runtime, _adapter, clock, _tracker):
        activate(runtime, 100)

        record = runtime.handle_event(
            event_with_onset(GestureAction.EXIT_REQUEST, 0, 1_500, Gesture.SHAKA),
            timings=FrameTimings(capture_ts_ns=1_500 * MS),
        )

        assert record is not None and record.accepted is True
        assert runtime.state is S.EXITING
        assert runtime.metrics.values("exit_request.gesture_response") == (1_500 * MS,)
        assert runtime.metrics.values("exit_request.capture_to_action") == (0,)
        at(clock, 1_500)
        runtime.shutdown()
        assert runtime.machine.terminated is True


def test_presentation_command_records_pipeline_dispatch_and_response() -> None:
    with session() as (runtime, adapter, clock, _tracker):
        activate(runtime, 100)
        at(clock, 250)

        runtime.handle_event(
            event_with_onset(
                GestureAction.NEXT_SLIDE, 200, 250, Gesture.OPEN_PALM_CLOCKWISE
            ),
            timings=FrameTimings(capture_ts_ns=250 * MS),
        )

        wait_for(
            lambda: adapter.executed == [Navigate(SlideDirection.NEXT)],
            "one next slide",
        )
        runtime.tick(at(clock, 250))

        assert runtime.metrics.values("next_slide.pipeline") == (50 * MS,)
        assert runtime.metrics.values("next_slide.dispatch") == (0,)
        assert runtime.metrics.values("next_slide.gesture_response") == (50 * MS,)
        assert runtime.metrics.values("next_slide.capture_to_action") == (0,)


def test_process_frame_records_ordered_stages_and_temporal_span() -> None:
    with session() as (runtime, _adapter, _clock, tracker):
        activate(runtime, 100)
        tracker.observations = (fist_observation(),)

        first = FrameTimings()
        assert runtime.process_frame(frame(200, 1, first)) is None
        second = FrameTimings()
        event = runtime.process_frame(frame(400, 2, second))

        assert event is not None
        assert event.action is GestureAction.PAUSE_TRACKING
        assert [span.stage for span in second.spans] == [
            Stage.FEATURE_EXTRACTION,
            Stage.CLASSIFICATION,
            Stage.TEMPORAL_CONFIRMATION,
        ]
        assert all(span.end_ns >= span.start_ns for span in second.spans)
        temporal = second.spans[-1]
        assert temporal.clock == "frame"
        assert (temporal.start_ns, temporal.end_ns) == (
            event.onset_ns,
            event.timestamp_ns,
        )


def test_handle_event_records_a_command_validation_span() -> None:
    with session() as (runtime, _adapter, _clock, _tracker):
        activate(runtime, 100)
        timings = FrameTimings()

        runtime.handle_event(
            event(GestureAction.NEXT_SLIDE, 200, Gesture.OPEN_PALM_CLOCKWISE),
            timings=timings,
        )

        assert [span.stage for span in timings.spans] == [Stage.COMMAND_VALIDATION]


def test_disabled_instrumentation_still_processes_frames_and_ticks() -> None:
    clock = Clock()
    tracker = FakeTracker((fist_observation(),))
    runtime = AirCueRuntime(
        Config(),
        source=FakeSource(),
        tracker=tracker,
        adapter=FakeAdapter(),
        clock_ns=clock,
        key_down=lambda _key: False,
        instrument=False,
    )
    assert runtime.initialize().accepted is True
    try:
        activate(runtime, 100)
        assert runtime.process_frame(frame(200, 1)) is None
        event = runtime.process_frame(frame(400, 2))
        assert event is not None and event.action is GestureAction.PAUSE_TRACKING

        runtime.tick(at(clock, 400))
        assert runtime.state is S.PAUSED
        assert runtime.metrics.names() == ()
    finally:
        runtime.close()
