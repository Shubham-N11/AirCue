"""Composition root: build, wire, and initialize the application's components."""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum

from aircue.capture.mailbox import FrameMailbox
from aircue.capture.opencv_source import OpenCvCameraSource
from aircue.capture.source import FrameSource
from aircue.capture.types import CaptureError, CaptureMode
from aircue.commands.click import ClickController
from aircue.commands.manager import CommandManager
from aircue.commands.pointer import PointerSmoother
from aircue.commands.scroll import ScrollController
from aircue.config.schema import Config
from aircue.dispatch.worker import CommandWorker
from aircue.gestures.recognizer import GestureRecognizer
from aircue.presentation.adapter import PresentationAdapter
from aircue.presentation.win32 import CtypesWin32
from aircue.presentation.win32_adapter import Win32Adapter
from aircue.presentation.win32_input import CtypesInput
from aircue.state.feedback import StatusFeedback, StatusIndicator, StatusModel
from aircue.state.machine import StateMachine, TransitionRecord
from aircue.state.recovery import RecoveryController
from aircue.state.safety import SafetyMonitor
from aircue.state.states import InteractionState
from aircue.state.transitions import TransitionTrigger
from aircue.vision.presence import PresenceReporter
from aircue.vision.primary import PrimaryHandSelector
from aircue.vision.tracker import HandTracker, MediaPipeHandTracker
from aircue.vision.types import TrackerError


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


class AirCueRuntime:
    """Owns the wired components and the INITIALIZING -> IDLE/ERROR transition."""

    def __init__(
        self,
        config: Config,
        *,
        source: FrameSource | None = None,
        tracker: HandTracker | None = None,
        adapter: PresentationAdapter | None = None,
        indicator: StatusIndicator | None = None,
        clock_ns: Callable[[], int] = time.monotonic_ns,
    ) -> None:
        self.config = config
        self.clock_ns = clock_ns
        self.machine = StateMachine()
        self.feedback = StatusFeedback(indicator or _SilentIndicator())
        self.manager = CommandManager()
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
        self._source = source
        self._tracker = tracker
        self._adapter = adapter
        self.source: FrameSource | None = None
        self.tracker: HandTracker | None = None
        self.adapter: PresentationAdapter | None = None
        self.worker: CommandWorker | None = None
        self.failure: StartupFailure | None = None

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

    def close(self) -> None:
        """Release the resources acquired by initialize."""
        if self.worker is not None:
            self.worker.stop()
            self.worker = None
        if self.tracker is not None:
            self.tracker.close()
            self.tracker = None
        if self.source is not None:
            self.source.close()
            self.source = None

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
        self.feedback.transition(record)
        return record
