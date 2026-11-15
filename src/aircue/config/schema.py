"""Typed configuration schema and validated defaults."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


def _bounded(default: Any, *, minimum: float | None = None, maximum: float | None = None) -> Any:
    metadata: dict[str, Any] = {}
    if minimum is not None:
        metadata["minimum"] = minimum
    if maximum is not None:
        metadata["maximum"] = maximum
    return field(default=default, metadata=metadata)


def _choice(default: str, choices: tuple[str, ...]) -> Any:
    return field(default=default, metadata={"choices": choices})


@dataclass(frozen=True)
class HotkeyConfig:
    activate: str = "ctrl+alt+a"
    deactivate: str = "ctrl+alt+d"
    exit: str = "ctrl+alt+q"


@dataclass(frozen=True)
class TimingConfig:
    activation_hold_ms: int = _bounded(800, minimum=1)
    resume_hold_ms: int = _bounded(250, minimum=1)
    fist_confirm_ms: int = _bounded(200, minimum=1)
    peace_confirm_ms: int = _bounded(250, minimum=1)
    shaka_hold_ms: int = _bounded(1500, minimum=1)
    gesture_cooldown_ms: int = _bounded(500, minimum=0)
    rearm_ms: int = _bounded(300, minimum=0)
    long_pinch_ms: int = _bounded(700, minimum=1)
    double_click_window_ms: int = _bounded(350, minimum=1)
    tracking_freeze_ms: int = _bounded(300, minimum=0)
    tracking_idle_ms: int = _bounded(1000, minimum=1)
    primary_hand_switch_ms: int = _bounded(500, minimum=0)
    camera_freeze_ms: int = _bounded(2000, minimum=1)
    target_refresh_ms: int = _bounded(250, minimum=1)
    target_stale_ms: int = _bounded(1000, minimum=1)
    adapter_deadline_ms: int = _bounded(150, minimum=1)
    adapter_unresponsive_ms: int = _bounded(300, minimum=1)
    metrics_window_s: float = _bounded(10.0, minimum=1.0)
    benchmark_warmup_s: float = _bounded(10.0, minimum=0.0)
    benchmark_measure_s: float = _bounded(60.0, minimum=0.0)
    instrumentation_block_s: float = _bounded(60.0, minimum=1.0)
    instrumentation_blocks: int = _bounded(5, minimum=1)


@dataclass(frozen=True)
class PinchConfig:
    close_threshold: float = _bounded(0.22, minimum=0.0, maximum=1.0)
    release_threshold: float = _bounded(0.32, minimum=0.0, maximum=1.0)
    rearm_threshold: float = _bounded(0.40, minimum=0.0, maximum=1.0)
    close_confirm_ms: int = _bounded(100, minimum=0)
    release_confirm_ms: int = _bounded(100, minimum=0)
    rearm_confirm_ms: int = _bounded(300, minimum=0)


@dataclass(frozen=True)
class RotationConfig:
    activation_deg: float = _bounded(25.0, minimum=0.0)
    neutral_band_deg: float = _bounded(8.0, minimum=0.0)
    continuous_enabled: bool = False
    repeat_step_deg: float = _bounded(30.0, minimum=0.0)
    repeat_interval_ms: int = _bounded(400, minimum=0)
    max_events_per_second: float = _bounded(2.0, minimum=0.0)


@dataclass(frozen=True)
class PointerConfig:
    dead_zone: float = _bounded(0.01, minimum=0.0, maximum=1.0)
    smoothing_min_alpha: float = _bounded(0.20, minimum=0.0, maximum=1.0)
    smoothing_max_alpha: float = _bounded(0.45, minimum=0.0, maximum=1.0)
    max_added_latency_ms: int = _bounded(40, minimum=0)
    sensitivity: float = _bounded(1.0, minimum=0.1, maximum=5.0)
    neutral_x: float = _bounded(0.5, minimum=0.0, maximum=1.0)
    neutral_y: float = _bounded(0.5, minimum=0.0, maximum=1.0)
    active_range: float = _bounded(0.4, minimum=0.0, maximum=1.0)


@dataclass(frozen=True)
class ScrollConfig:
    dead_zone: float = _bounded(0.05, minimum=0.0, maximum=1.0)
    max_notches_per_second: float = _bounded(10.0, minimum=0.0)
    speed_notches_per_second: float = _bounded(10.0, minimum=0.0)
    invert: bool = False


@dataclass(frozen=True)
class CameraConfig:
    device_index: int = _bounded(0, minimum=0)
    reconnect_attempts: int = _bounded(3, minimum=0)
    reconnect_backoff_ms: int = _bounded(500, minimum=0)


@dataclass(frozen=True)
class VisionConfig:
    confidence_threshold: float = _bounded(0.5, minimum=0.0, maximum=1.0)
    max_hands: int = _bounded(2, minimum=1)


@dataclass(frozen=True)
class GestureConfig:
    finger_extended_angle_deg: float = _bounded(160.0, minimum=0.0, maximum=180.0)
    pointer_min_separation: float = _bounded(0.40, minimum=0.0)


@dataclass(frozen=True)
class DispatchConfig:
    queue_size: int = _bounded(8, minimum=1)
    pointer_ttl_ms: int = _bounded(100, minimum=1)
    scroll_ttl_ms: int = _bounded(150, minimum=1)
    click_ttl_ms: int = _bounded(250, minimum=1)
    navigation_ttl_ms: int = _bounded(500, minimum=1)


@dataclass(frozen=True)
class TierConfig:
    width: int = _bounded(640, minimum=1)
    height: int = _bounded(360, minimum=1)
    min_fps: float = _bounded(10.0, minimum=1.0)
    max_fps: float = _bounded(15.0, minimum=1.0)
    recognition_compute_p95_ms: float = _bounded(50.0, minimum=0.0)
    base_latency_p50_ms: float = _bounded(100.0, minimum=0.0)
    base_latency_p95_ms: float = _bounded(150.0, minimum=0.0)


@dataclass(frozen=True)
class HardwareConfig:
    profile: str = _choice("auto", ("auto", "tier1", "tier2", "tier3"))
    backend: str = _choice("auto", ("auto", "cpu", "gpu"))
    processing_fps: float = _bounded(0.0, minimum=0.0, maximum=240.0)
    tier1: TierConfig = field(default_factory=TierConfig)
    tier2: TierConfig = field(
        default_factory=lambda: TierConfig(
            width=1280,
            height=720,
            min_fps=20.0,
            max_fps=30.0,
            recognition_compute_p95_ms=35.0,
            base_latency_p50_ms=70.0,
            base_latency_p95_ms=100.0,
        )
    )
    tier3: TierConfig = field(
        default_factory=lambda: TierConfig(
            width=1280,
            height=720,
            min_fps=30.0,
            max_fps=60.0,
            recognition_compute_p95_ms=35.0,
            base_latency_p50_ms=70.0,
            base_latency_p95_ms=100.0,
        )
    )


@dataclass(frozen=True)
class DiagnosticsConfig:
    log_level: str = _choice("INFO", ("DEBUG", "INFO", "WARNING", "ERROR"))
    debug_capture: bool = False
    debug_capture_dir: str = ""


@dataclass(frozen=True)
class UiConfig:
    overlay_enabled: bool = True
    overlay_opacity: float = _bounded(0.85, minimum=0.1, maximum=1.0)


@dataclass(frozen=True)
class Config:
    hotkeys: HotkeyConfig = field(default_factory=HotkeyConfig)
    timing: TimingConfig = field(default_factory=TimingConfig)
    pinch: PinchConfig = field(default_factory=PinchConfig)
    rotation: RotationConfig = field(default_factory=RotationConfig)
    pointer: PointerConfig = field(default_factory=PointerConfig)
    scroll: ScrollConfig = field(default_factory=ScrollConfig)
    camera: CameraConfig = field(default_factory=CameraConfig)
    vision: VisionConfig = field(default_factory=VisionConfig)
    gestures: GestureConfig = field(default_factory=GestureConfig)
    dispatch: DispatchConfig = field(default_factory=DispatchConfig)
    hardware: HardwareConfig = field(default_factory=HardwareConfig)
    diagnostics: DiagnosticsConfig = field(default_factory=DiagnosticsConfig)
    ui: UiConfig = field(default_factory=UiConfig)
