"""Composition root and four-thread session loop from design.md D4."""

from __future__ import annotations

import logging
import queue
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Generic, TypeVar

from aircue.app.hotkeys import HotkeyAction, HotkeyPoller
from aircue.capture.mailbox import CaptureThread, FrameMailbox
from aircue.capture.opencv_source import OpenCvCameraSource
from aircue.capture.source import FrameSource
from aircue.capture.types import CaptureError, CaptureMode, Frame
from aircue.commands.click import ClickController, gate_click
from aircue.commands.commands import Command
from aircue.commands.manager import CommandManager
from aircue.commands.pointer import (
    PointerSmoother,
    check_pointer_movement,
    map_pointer,
)
from aircue.commands.scroll import ScrollController
from aircue.config.schema import Config
from aircue.diagnostics.session_log import record_event
from aircue.dispatch.errors import apply_error
from aircue.dispatch.worker import CommandWorker
from aircue.gestures.classifiers import is_pointer_pose
from aircue.gestures.recognizer import GestureRecognizer
from aircue.gestures.semantic import GestureAction, SemanticEvent
from aircue.gestures.vocabulary import Gesture
from aircue.presentation.adapter import (
    CommandPayload,
    Navigate,
    PointerMove,
    PresentationAdapter,
    Scroll,
    SlideDirection,
)
from aircue.presentation.target import TargetKind, TargetSnapshot
from aircue.presentation.win32 import CtypesKeyState, CtypesWin32
from aircue.presentation.win32_adapter import Win32Adapter
from aircue.presentation.win32_input import CtypesInput
from aircue.state.activation import ActivationController, ActivationSource
from aircue.state.feedback import StatusFeedback, StatusIndicator, StatusModel
from aircue.state.machine import StateMachine, TransitionRecord
from aircue.state.recovery import RecoveryController
from aircue.state.safety import SafetyMonitor
from aircue.state.states import InteractionState
from aircue.state.transitions import TransitionTrigger
from aircue.vision.features import extract_hand_record
from aircue.vision.presence import PresenceReporter
from aircue.vision.primary import PrimaryHandSelector
from aircue.vision.tracker import HandTracker, MediaPipeHandTracker
from aircue.vision.types import (
    INDEX_TIP,
    WRIST,
    HandRecord,
    InvalidLandmarkFrameError,
    Landmark,
    TrackerError,
)

logger = logging.getLogger("aircue.runtime")

_TICK_INTERVAL_S = 0.01
_EVENT_QUEUE_SIZE = 16
_JOIN_TIMEOUT_S = 1.0


class StartupComponent(StrEnum):
    CONFIG = "config"
    CAMERA = "camera"
    TRACKER = "tracker"
    ADAPTER = "adapter"


class _SilentIndicator:
    def update(self, status: StatusModel) -> None:
        """The overlay lands with task 7.4; startup must not depend on it."""


@dataclass(frozen=True)
class StartupFailure:
    component: StartupComponent
    detail: str


@dataclass(frozen=True)
class HandSample:
    """The newest primary hand, published once per processed frame."""

    hand: HandRecord | None
    timestamp_ns: int
    present: bool
    absent_since_ns: int | None = None


T = TypeVar("T")


class _LatestSlot(Generic[T]):
    """Holds at most one unchecked sample; a newer sample replaces the older one."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._value: T | None = None

    def publish(self, value: T) -> None:
        with self._lock:
            self._value = value

    def take(self) -> T | None:
        with self._lock:
            value = self._value
            self._value = None
            return value


class AirCueRuntime:
    """Owns the wired components, the session threads, and the state loop."""

    def __init__(
        self,
        config: Config,
        *,
        source: FrameSource | None = None,
        tracker: HandTracker | None = None,
        adapter: PresentationAdapter | None = None,
        indicator: StatusIndicator | None = None,
        clock_ns: Callable[[], int] = time.monotonic_ns,
        key_down: Callable[[int], bool] | None = None,
    ) -> None:
        self.config = config
        self.clock_ns = clock_ns
        self.machine = StateMachine()
        self.feedback = StatusFeedback(indicator or _SilentIndicator())
        self.manager = CommandManager()
        self.activation = ActivationController()
        self.hotkeys = HotkeyPoller(
            config.hotkeys, key_down or CtypesKeyState().pressed
        )
        self.recognizer = GestureRecognizer(config)
        self.clicks = ClickController(
            self.machine, double_click_window_ms=config.timing.double_click_window_ms
        )
        self.pointer = PointerSmoother(
            dead_zone=config.pointer.dead_zone,
            min_alpha=config.pointer.smoothing_min_alpha,
            max_alpha=config.pointer.smoothing_max_alpha,
            max_added_latency_ms=config.pointer.max_added_latency_ms,
        )
        self.scroll = ScrollController(
            self.manager,
            dead_zone=config.scroll.dead_zone,
            neutral_y=config.pointer.neutral_y,
            speed_notches_per_second=config.scroll.speed_notches_per_second,
            max_notches_per_second=config.scroll.max_notches_per_second,
            invert=config.scroll.invert,
        )
        self.selection = PrimaryHandSelector(
            switch_window_ms=config.timing.primary_hand_switch_ms,
            match_distance=config.vision.primary_match_distance,
        )
        self.presence = PresenceReporter()
        self.safety = SafetyMonitor(
            freeze_ms=config.timing.tracking_freeze_ms,
            idle_ms=config.timing.tracking_idle_ms,
        )
        self.recovery = RecoveryController(
            self.machine,
            reconnect_attempts=config.camera.reconnect_attempts,
            reconnect_backoff_ms=config.camera.reconnect_backoff_ms,
        )
        self.frames = FrameMailbox()
        self.events: queue.Queue[SemanticEvent] = queue.Queue(maxsize=_EVENT_QUEUE_SIZE)
        self.hands = _LatestSlot[HandSample]()
        self._source = source
        self._tracker = tracker
        self._adapter = adapter
        self.source: FrameSource | None = None
        self.tracker: HandTracker | None = None
        self.adapter: PresentationAdapter | None = None
        self.worker: CommandWorker | None = None
        self.failure: StartupFailure | None = None

        self._stop_event = threading.Event()
        self._capture: CaptureThread | None = None
        self._vision_thread: threading.Thread | None = None
        self._capture_error = ""
        self._vision_error: str | None = None
        self._dropped_events = 0
        self._invalid_frames = 0
        self._last_capture_count = 0
        self._last_capture_ns: int | None = None
        self._last_target_kind: TargetKind | None = None

    @property
    def state(self) -> InteractionState:
        return self.machine.state

    def initialize(self) -> TransitionRecord:
        """Open the camera and load the tracker; error out with the failing component."""
        now = self.clock_ns()
        try:
            self.source = self._source or OpenCvCameraSource(self.config.camera.device_index)
            self.source.open(self._capture_mode())
        except CaptureError as exc:
            return self._fail(StartupComponent.CAMERA, str(exc), now)
        except Exception as exc:
            return self._fail(StartupComponent.CAMERA, str(exc), now)

        try:
            self.tracker = self._tracker or MediaPipeHandTracker(
                self.config.vision.model_path,
                confidence_threshold=self.config.vision.confidence_threshold,
                max_hands=self.config.vision.max_hands,
            )
        except TrackerError as exc:
            return self._fail(StartupComponent.TRACKER, str(exc), now)
        except Exception as exc:
            return self._fail(StartupComponent.TRACKER, str(exc), now)

        try:
            self.adapter = self._adapter or Win32Adapter(
                CtypesWin32(),
                CtypesInput(),
                refresh_ms=self.config.timing.target_refresh_ms,
                stale_ms=self.config.timing.target_stale_ms,
            )
        except Exception as exc:
            return self._fail(StartupComponent.ADAPTER, str(exc), now)

        self.worker = CommandWorker(
            self.adapter,
            lambda: self.machine.generation,
            queue_size=self.config.dispatch.queue_size,
            pointer_ttl_ms=self.config.dispatch.pointer_ttl_ms,
            scroll_ttl_ms=self.config.dispatch.scroll_ttl_ms,
            click_ttl_ms=self.config.dispatch.click_ttl_ms,
            navigation_ttl_ms=self.config.dispatch.navigation_ttl_ms,
            deadline_ms=self.config.timing.adapter_deadline_ms,
            unresponsive_ms=self.config.timing.adapter_unresponsive_ms,
            refresh_ms=self.config.timing.target_refresh_ms,
            clock_ns=self.clock_ns,
        )
        record = self.machine.apply(
            TransitionTrigger.INITIALIZATION_SUCCEEDED,
            now,
            reason="camera, tracker, and adapter ready",
        )
        self.feedback.transition(record)
        return record

    def run(self, stop: threading.Event | None = None) -> None:
        """Start capture, vision, and command workers, then drive the state loop."""
        if self.source is None or self.tracker is None or self.worker is None:
            raise RuntimeError("initialize the runtime before run()")
        self._stop_event = stop if stop is not None else threading.Event()
        self._vision_error = None
        self._capture_error = ""
        self._last_target_kind = None
        self._last_capture_count = 0
        self._last_capture_ns = self.clock_ns()

        self._capture = CaptureThread(
            self.source, self.frames, on_error=self._record_capture_error
        )
        self._vision_thread = threading.Thread(
            target=self._vision_loop, name="aircue-vision", daemon=True
        )
        self.worker.start()
        self._capture.start()
        self._vision_thread.start()
        try:
            while not self._stop_event.is_set() and not self.machine.terminated:
                self.tick()
                self._stop_event.wait(_TICK_INTERVAL_S)
        except KeyboardInterrupt:
            self.request_exit()
        finally:
            self.shutdown()

    def request_exit(self) -> TransitionRecord:
        """Apply the exit request from any running state."""
        return self._transition(
            TransitionTrigger.EXIT_REQUEST,
            self.clock_ns(),
            reason="exit requested",
        )

    def shutdown(self) -> None:
        """Release every resource, then complete EXITING if it was entered."""
        self.close()
        if self.state is InteractionState.EXITING and not self.machine.terminated:
            record = self.machine.apply(
                TransitionTrigger.CLEANUP_COMPLETED,
                self.clock_ns(),
                reason="resources released",
            )
            self.feedback.transition(record)

    def close(self) -> None:
        """Release the resources acquired by initialize and run."""
        self._stop_event.set()
        if self._capture is not None:
            self._capture.stop()
            self._capture = None
        self.frames.close()

        vision = self._vision_thread
        self._vision_thread = None
        vision_alive = False
        if vision is not None:
            vision.join(_JOIN_TIMEOUT_S)
            vision_alive = vision.is_alive()
            if vision_alive:
                logger.error(
                    "vision worker did not stop within %.1f s; abandoning it",
                    _JOIN_TIMEOUT_S,
                )

        if self.worker is not None:
            self.worker.stop()
            self.worker = None
        if self.tracker is not None:
            if not vision_alive:
                self.tracker.close()
            self.tracker = None
        if self.source is not None:
            self.source.close()
            self.source = None

    def process_frame(self, frame: Frame) -> SemanticEvent | None:
        """Run one captured frame through tracking, features, and recognition."""
        if self.tracker is None:
            return None
        timestamp_ns = frame.capture_ts_ns
        try:
            observations = self.tracker.detect(frame)
            selection = self.selection.update(observations, timestamp_ns)
            hand = (
                extract_hand_record(
                    selection.observation,
                    confidence_threshold=self.config.vision.confidence_threshold,
                    finger_extended_angle_deg=self.config.gestures.finger_extended_angle_deg,
                )
                if selection.observation is not None
                else None
            )
        except InvalidLandmarkFrameError:
            self._invalid_frames += 1
            self.hands.publish(HandSample(None, timestamp_ns, False))
            self.recognizer.update(None, self.state, timestamp_ns, sequence=frame.sequence)
            return None
        except Exception as exc:
            self._record_vision_error(str(exc))
            return None

        presence = self.presence.observe(hand is not None, timestamp_ns)
        self.hands.publish(
            HandSample(hand, timestamp_ns, presence.present, presence.first_absence_ts_ns)
        )
        event = self.recognizer.update(
            None if (selection.suppress_recognition or hand is None) else hand,
            self.state,
            timestamp_ns,
            sequence=frame.sequence,
        )
        if event is not None:
            record_event(
                "gesture",
                generation=self.machine.generation,
                action=event.action.value,
                gesture=event.gesture.value,
                confidence=event.confidence,
                onset_ns=event.onset_ns,
                timestamp_ns=event.timestamp_ns,
                sequence=frame.sequence,
            )
            try:
                self.events.put_nowait(event)
            except queue.Full:
                self._dropped_events += 1
                logger.warning("semantic event queue is full; dropped %r", event.action)
        return event

    def handle_event(self, event: SemanticEvent) -> TransitionRecord | None:
        """Apply one semantic event on the state thread, revalidating its target."""
        action = event.action
        timestamp_ns = event.timestamp_ns
        record_event(
            "state",
            generation=self.machine.generation,
            state=self.state.value,
            action=action.value,
            timestamp_ns=timestamp_ns,
        )

        if action is GestureAction.EXIT_REQUEST:
            return self._transition(
                TransitionTrigger.EXIT_REQUEST, timestamp_ns, reason="gesture exit"
            )
        if action is GestureAction.PAUSE_TRACKING:
            return self._transition(
                TransitionTrigger.FIST_CONFIRMED, timestamp_ns, reason="fist confirmed"
            )
        if action is GestureAction.ACTIVATE:
            return self._activation(ActivationSource.GESTURE, timestamp_ns)
        if action is GestureAction.RESUME_TRACKING:
            return self._activation(ActivationSource.GESTURE, timestamp_ns)
        if action is GestureAction.ENTER_POINTER_MODE:
            return self._mode_change(
                Command.ENTER_POINTER_MODE,
                TransitionTrigger.PINCH_CONFIRMED,
                timestamp_ns,
            )
        if action is GestureAction.ENTER_SCROLL_MODE:
            return self._mode_change(
                Command.ENTER_SCROLL_MODE,
                TransitionTrigger.PEACE_CONFIRMED,
                timestamp_ns,
            )
        if action is GestureAction.EXIT_SCROLL_MODE:
            return self._mode_change(
                Command.EXIT_SCROLL_MODE,
                TransitionTrigger.PEACE_CONFIRMED,
                timestamp_ns,
            )
        if action in (GestureAction.NEXT_SLIDE, GestureAction.PREV_SLIDE):
            self._navigate(action, timestamp_ns)
            return None
        if action is GestureAction.CLICK_CANDIDATE or (
            action is GestureAction.EXIT_POINTER_MODE
            and event.gesture is Gesture.PINCH
        ):
            return self._click(event)
        return None

    def tick(self, now_ns: int | None = None) -> None:
        """One state-thread iteration: faults, outcomes, events, samples, timers."""
        now = self.clock_ns() if now_ns is None else now_ns
        self._apply_pending_faults(now)
        self._poll_hotkeys(now)
        self._drain_outcomes(now)
        self._drain_events()
        sample = self.hands.take()
        if sample is not None:
            self._observe_hand(sample, now)
        self._emit_pointer(sample)
        self._emit_scroll(sample)
        self._expire_click(now)
        self._update_target(now)
        self._check_camera(now)

    def _vision_loop(self) -> None:
        while not self._stop_event.is_set():
            frame = self.frames.take(0.1)
            if frame is None:
                continue
            self.process_frame(frame)
            if self._vision_error is not None:
                return

    def _activation(
        self, source: ActivationSource, timestamp_ns: int
    ) -> TransitionRecord | None:
        snapshot = self._snapshot(timestamp_ns)
        decision = self.activation.evaluate(
            self.state,
            snapshot.kind,
            source,
            target_ready=self._foreground(snapshot),
        )
        if not decision.accepted:
            logger.info("activation rejected: %s", decision.reason)
            return None
        assert decision.trigger is not None
        logger.info("activation accepted via %s", source.value)
        return self._transition(decision.trigger, timestamp_ns, reason=decision.reason or None)

    def _poll_hotkeys(self, now_ns: int) -> None:
        for action in self.hotkeys.poll():
            record: TransitionRecord | None
            if action is HotkeyAction.EXIT:
                record = self._transition(
                    TransitionTrigger.EXIT_REQUEST,
                    now_ns,
                    reason=f"hotkey: {self.hotkeys.spec(action)}",
                )
            elif action is HotkeyAction.DEACTIVATE:
                record = self._transition(
                    TransitionTrigger.DEACTIVATION_HOTKEY,
                    now_ns,
                    reason=f"hotkey: {self.hotkeys.spec(action)}",
                )
            else:
                record = self._activation(ActivationSource.HOTKEY, now_ns)
            effect = (
                f"-> {record.resulting.value}"
                if record is not None and record.accepted
                else "no effect"
            )
            logger.info("hotkey %s: %s", self.hotkeys.spec(action), effect)

    def _mode_change(
        self,
        command: Command,
        trigger: TransitionTrigger,
        timestamp_ns: int,
    ) -> TransitionRecord | None:
        snapshot = self._snapshot(timestamp_ns)
        decision = self.manager.validate(command, self.state, snapshot.capabilities)
        if not decision.allowed:
            logger.info("mode change rejected: %s", decision.reason)
            return None
        return self._transition(trigger, timestamp_ns, reason=command.value)

    def _navigate(self, action: GestureAction, timestamp_ns: int) -> None:
        if action is GestureAction.NEXT_SLIDE:
            command, direction = Command.NEXT_SLIDE, SlideDirection.NEXT
        else:
            command, direction = Command.PREVIOUS_SLIDE, SlideDirection.PREVIOUS
        snapshot = self._snapshot(timestamp_ns)
        decision = self.manager.validate(command, self.state, snapshot.capabilities)
        if not decision.allowed:
            logger.info("navigation rejected: %s", decision.reason)
            return
        self._submit(Navigate(direction), timestamp_ns)

    def _click(self, event: SemanticEvent) -> TransitionRecord | None:
        update = self.clicks.on_event(event)
        if update.dispatch is not None:
            snapshot = self._snapshot(event.timestamp_ns)
            decision = gate_click(
                self.manager,
                update.dispatch,
                self.state,
                snapshot.capabilities,
                foreground=self._foreground(snapshot),
            )
            if decision.payload is not None:
                self._submit(decision.payload, event.timestamp_ns)
            else:
                logger.info("click rejected: %s", decision.reason)
        if update.transition is not None:
            self._after_transition(update.transition)
        return update.transition

    def _observe_hand(self, sample: HandSample, now_ns: int) -> None:
        report = self.safety.tracking(
            sample.present,
            now_ns,
            first_absence_ns=sample.absent_since_ns,
        )
        if report.output_frozen:
            self.clicks.cancel()
            self.pointer.invalidate()
            self.scroll.reset()
        if report.trigger is not None:
            self._transition(report.trigger, now_ns, reason=report.status.value)

    def _emit_pointer(self, sample: HandSample | None) -> None:
        if sample is None or self.state is not InteractionState.POINTER_MODE:
            return
        snapshot = self._snapshot(sample.timestamp_ns)
        point = self._pointer_point(sample.hand)
        decision = check_pointer_movement(
            self.manager,
            self.state,
            snapshot.capabilities,
            pointer_valid=point is not None,
            pinch_closed=self.recognizer.pinch_closed,
            click_pending=self.clicks.pending,
        )
        if not decision.allowed:
            self.pointer.invalidate()
            return
        smoothed = self.pointer.update(point, sample.timestamp_ns)
        if smoothed is None:
            return
        mapped = map_pointer(
            smoothed[0],
            smoothed[1],
            snapshot.monitor_bounds,
            dead_zone=self.config.pointer.dead_zone,
            neutral_x=self.config.pointer.neutral_x,
            neutral_y=self.config.pointer.neutral_y,
            active_range=self.config.pointer.active_range,
            sensitivity=self.config.pointer.sensitivity,
        )
        if mapped is not None:
            self._submit(PointerMove(*mapped), sample.timestamp_ns)

    def _emit_scroll(self, sample: HandSample | None) -> None:
        if sample is None or self.state is not InteractionState.SCROLL_MODE:
            return
        snapshot = self._snapshot(sample.timestamp_ns)
        update = self.scroll.update(
            self._hand_y(sample.hand),
            sample.timestamp_ns,
            self.state,
            snapshot.capabilities,
            foreground=self._foreground(snapshot),
        )
        if update.notches:
            self._submit(Scroll(update.notches), sample.timestamp_ns)

    def _expire_click(self, now_ns: int) -> None:
        dispatch = self.clicks.advance(now_ns)
        if dispatch is None:
            return
        snapshot = self._snapshot(now_ns)
        decision = gate_click(
            self.manager,
            dispatch,
            self.state,
            snapshot.capabilities,
            foreground=self._foreground(snapshot),
        )
        if decision.payload is not None:
            self._submit(decision.payload, now_ns)
        else:
            logger.info("click rejected: %s", decision.reason)

    def _drain_events(self) -> None:
        while True:
            try:
                event = self.events.get_nowait()
            except queue.Empty:
                return
            self.handle_event(event)

    def _drain_outcomes(self, now_ns: int) -> None:
        if self.worker is None:
            return
        for outcome in self.worker.drain_outcomes():
            if outcome.error is None:
                continue
            record = apply_error(
                self.machine, outcome.error, now_ns, detail=outcome.detail
            )
            if record is not None and record.accepted:
                record_event(
                    "fault",
                    generation=record.generation,
                    level=logging.ERROR,
                    reason=outcome.error.value,
                    detail=outcome.detail,
                    timestamp_ns=now_ns,
                )
            self._after_transition(record)
        if self.worker.check_unresponsive(now_ns):
            self._transition(
                TransitionTrigger.UNRECOVERABLE_ADAPTER_ERROR,
                now_ns,
                reason="adapter unresponsive",
            )

    def _apply_pending_faults(self, now_ns: int) -> None:
        error = self._vision_error
        if error is None:
            return
        self._vision_error = None
        self._fault(self._vision_fault_trigger(), now_ns, error)

    def _check_camera(self, now_ns: int) -> None:
        capture = self._capture
        if capture is None:
            return
        count = capture.frames_captured
        if count != self._last_capture_count:
            self._last_capture_count = count
            self._last_capture_ns = now_ns
            return
        if self._last_capture_ns is None:
            self._last_capture_ns = now_ns
            return
        freeze_ns = self.config.timing.camera_freeze_ms * 1_000_000
        if now_ns - self._last_capture_ns <= freeze_ns:
            return
        self._last_capture_ns = now_ns
        self._fault(
            TransitionTrigger.CAMERA_FAULT,
            now_ns,
            self._capture_error or "no camera frame within the freeze window",
        )

    def _update_target(self, now_ns: int) -> None:
        if self.adapter is None:
            return
        snapshot = self.adapter.snapshot()
        if snapshot.kind is not self._last_target_kind:
            self._last_target_kind = snapshot.kind
            self.feedback.target_changed(snapshot.kind)
        trigger = self.safety.focus_changed(self._foreground(snapshot))
        if trigger is not None:
            self._transition(
                trigger, now_ns, reason=f"target is {snapshot.kind.value}"
            )

    def _fault(
        self, trigger: TransitionTrigger, timestamp_ns: int, detail: str
    ) -> TransitionRecord:
        record = self.recovery.fault(trigger, timestamp_ns, reason=detail)
        record_event(
            "fault",
            generation=record.generation,
            level=logging.ERROR,
            reason=detail,
            trigger=trigger.value,
            timestamp_ns=timestamp_ns,
        )
        self._after_transition(record)
        return record

    def _vision_fault_trigger(self) -> TransitionTrigger:
        if self.state in (
            InteractionState.ACTIVE,
            InteractionState.POINTER_MODE,
            InteractionState.SCROLL_MODE,
        ):
            return TransitionTrigger.UNRECOVERABLE_INTERNAL_FAULT
        return TransitionTrigger.UNRECOVERABLE_FAULT

    def _transition(
        self,
        trigger: TransitionTrigger,
        timestamp_ns: int,
        *,
        reason: str | None = None,
    ) -> TransitionRecord:
        record = self.machine.apply(trigger, timestamp_ns, reason=reason)
        self._after_transition(record)
        return record

    def _after_transition(self, record: TransitionRecord | None) -> None:
        if record is None:
            return
        record_event(
            "state",
            generation=record.generation,
            accepted=record.accepted,
            previous=record.previous.value,
            trigger=record.trigger.value,
            resulting=record.resulting.value,
            reason=record.reason,
            timestamp_ns=record.timestamp_ns,
        )
        if not record.accepted:
            return
        self.feedback.transition(record)
        if record.resulting is not InteractionState.POINTER_MODE:
            self.clicks.cancel()
            self.pointer.invalidate()
        if record.resulting is not InteractionState.SCROLL_MODE:
            self.scroll.reset()
        if record.resulting is InteractionState.EXITING:
            self._stop_event.set()

    def _submit(self, payload: CommandPayload, timestamp_ns: int) -> bool:
        if self.worker is None:
            return False
        return self.worker.submit(
            payload,
            generation=self.machine.generation,
            target=self._snapshot(timestamp_ns),
            now_ns=timestamp_ns,
        )

    def _snapshot(self, timestamp_ns: int) -> TargetSnapshot:
        if self.adapter is not None:
            return self.adapter.snapshot()
        return TargetSnapshot(captured_ns=timestamp_ns)

    @staticmethod
    def _foreground(snapshot: TargetSnapshot) -> bool:
        return snapshot.kind is not TargetKind.UNKNOWN

    @staticmethod
    def _landmark(hand: HandRecord | None, index: int) -> Landmark | None:
        if hand is None or index >= len(hand.landmarks) or index >= len(hand.valid):
            return None
        if not hand.valid[index]:
            return None
        return hand.landmarks[index]

    def _pointer_point(self, hand: HandRecord | None) -> tuple[float, float] | None:
        if hand is None or not is_pointer_pose(
            hand, self.config.gestures.pointer_min_separation
        ):
            return None
        tip = self._landmark(hand, INDEX_TIP)
        return None if tip is None else (tip.x, tip.y)

    def _hand_y(self, hand: HandRecord | None) -> float | None:
        for index in (INDEX_TIP, WRIST):
            landmark = self._landmark(hand, index)
            if landmark is not None:
                return landmark.y
        return None

    def _record_capture_error(self, error: CaptureError) -> None:
        detail = str(error)
        if detail != self._capture_error:
            record_event(
                "fault",
                generation=self.machine.generation,
                level=logging.WARNING,
                reason="camera read failed",
                detail=detail,
                timestamp_ns=self.clock_ns(),
            )
        self._capture_error = detail

    def _record_vision_error(self, detail: str) -> None:
        if self._vision_error is None:
            record_event(
                "fault",
                generation=self.machine.generation,
                level=logging.ERROR,
                reason="vision pipeline failed",
                detail=detail,
                timestamp_ns=self.clock_ns(),
            )
        self._vision_error = detail

    def _capture_mode(self) -> CaptureMode:
        tier = self.config.hardware.tier2
        return CaptureMode(tier.width, tier.height, tier.max_fps)

    def _fail(
        self, component: StartupComponent, detail: str, timestamp_ns: int
    ) -> TransitionRecord:
        self.failure = StartupFailure(component, detail)
        self.close()
        record = self.machine.apply(
            TransitionTrigger.INITIALIZATION_FAILED,
            timestamp_ns,
            reason=f"{component.value}: {detail}",
        )
        record_event(
            "fault",
            generation=record.generation,
            level=logging.ERROR,
            reason=f"{component.value}: {detail}",
            timestamp_ns=timestamp_ns,
        )
        self.feedback.transition(record)
        return record
