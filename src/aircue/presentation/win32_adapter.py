"""Win32 presentation adapter: revalidate the target, then synthesize one command."""

from __future__ import annotations

import time
from collections.abc import Callable

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
from aircue.presentation.cache import TargetCache
from aircue.presentation.discovery import DiscoveryResult, PowerPointDiscovery, Win32Api
from aircue.presentation.input import InputSink
from aircue.presentation.target import Capability, ScreenRect, TargetKind, TargetSnapshot
from aircue.presentation.win32_input import VK_NEXT, VK_PRIOR

_NAVIGATION_KEYS = {SlideDirection.NEXT: VK_NEXT, SlideDirection.PREVIOUS: VK_PRIOR}


def _required_capability(payload: CommandPayload) -> Capability:
    return Capability.NAVIGATION if isinstance(payload, Navigate) else Capability.POINTER


class Win32Adapter:
    """The fail-closed adapter from design.md D5.

    Every payload is revalidated against a fresh discovery immediately before
    synthesis. A changed process, window, kind, focus, or monitor rejects the
    payload and sends nothing.
    """

    def __init__(
        self,
        api: Win32Api,
        sink: InputSink,
        *,
        refresh_ms: int = 250,
        stale_ms: int = 1000,
        clock_ns: Callable[[], int] = time.monotonic_ns,
    ) -> None:
        self._discovery = PowerPointDiscovery(api)
        self._cache = TargetCache(refresh_ms=refresh_ms, stale_ms=stale_ms)
        self._sink = sink
        self._clock_ns = clock_ns

    def snapshot(self) -> TargetSnapshot:
        return self._cache.snapshot(self._clock_ns())

    def refresh(self) -> TargetSnapshot:
        return self._cache.refresh(self._discovery.discover(), self._clock_ns())

    def execute(self, payload: CommandPayload) -> AdapterResult:
        cached = self.snapshot()
        if cached.kind is TargetKind.UNKNOWN:
            return AdapterResult(AdapterError.TARGET_UNAVAILABLE, "no fresh presentation target")
        if not cached.capabilities.supports(_required_capability(payload)):
            if cached.kind is TargetKind.PRESENTER_VIEW:
                return AdapterResult(
                    AdapterError.UNSUPPORTED_PRESENTER_VIEW,
                    f"{type(payload).__name__} is not available in Presenter View",
                )
            return AdapterResult(
                AdapterError.TARGET_UNAVAILABLE,
                f"{cached.kind.value} provides no presentation capabilities",
            )

        discovery = self._discovery.discover()
        if not discovery.available:
            return AdapterResult(
                AdapterError.ADAPTER_UNAVAILABLE,
                "PowerPoint is not running" + _errors(discovery),
            )
        foreground = next(
            (window for window in discovery.windows if window.visible and window.foreground),
            None,
        )
        if foreground is None:
            return AdapterResult(
                AdapterError.FOCUS_LOST, "no PowerPoint window is foreground" + _describe(discovery)
            )

        fresh = self._cache.refresh(discovery, self._clock_ns())
        if fresh.kind is TargetKind.UNKNOWN:
            return AdapterResult(
                AdapterError.TARGET_UNAVAILABLE,
                "the foreground window is ambiguous" + _describe(discovery),
            )
        changed = _changed_fields(cached, fresh, foreground.handle)
        if changed:
            return AdapterResult(
                AdapterError.TARGET_CHANGED,
                "target changed: " + ", ".join(changed) + _describe(discovery),
            )
        if isinstance(payload, PointerMove) and not _contains(fresh.monitor_bounds, payload):
            return AdapterResult(
                AdapterError.TARGET_CHANGED,
                f"({payload.x}, {payload.y}) is outside the slideshow monitor "
                f"{fresh.monitor_bounds}",
            )
        return self._synthesize(payload)

    def _synthesize(self, payload: CommandPayload) -> AdapterResult:
        match payload:
            case Navigate(direction):
                sent = self._sink.key(_NAVIGATION_KEYS[direction])
            case PointerMove(x, y):
                sent = self._sink.move(x, y)
            case Click():
                sent = self._sink.click(double=False)
            case DoubleClick():
                sent = self._sink.click(double=True)
            case Scroll(notches):
                sent = self._sink.wheel(notches)
            case _:
                return AdapterResult(AdapterError.INTERNAL, f"unknown payload {payload!r}")
        if not sent:
            return AdapterResult(
                AdapterError.INPUT_BLOCKED,
                "SendInput injected no input; a higher-integrity window may have focus",
            )
        return AdapterResult()


def _changed_fields(
    cached: TargetSnapshot, fresh: TargetSnapshot, foreground: int
) -> list[str]:
    changes: list[str] = []
    if fresh.process_id != cached.process_id:
        changes.append(f"process {cached.process_id} -> {fresh.process_id}")
    if fresh.kind is not cached.kind:
        changes.append(f"kind {cached.kind.value} -> {fresh.kind.value}")
    if foreground == cached.window_handle:
        if fresh.window_handle != cached.window_handle:
            changes.append(f"window {cached.window_handle:#x} -> {fresh.window_handle:#x}")
        if fresh.output_handle != cached.output_handle:
            changes.append(f"output {cached.output_handle:#x} -> {fresh.output_handle:#x}")
    elif foreground != cached.output_handle:
        changes.append(f"foreground {foreground:#x} is not the cached target")
    if fresh.monitor_bounds != cached.monitor_bounds:
        changes.append(f"monitor {cached.monitor_bounds} -> {fresh.monitor_bounds}")
    return changes


def _contains(rect: ScreenRect | None, point: PointerMove) -> bool:
    return (
        rect is not None
        and rect.left <= point.x < rect.right
        and rect.top <= point.y < rect.bottom
    )


def _describe(discovery: DiscoveryResult) -> str:
    if not discovery.windows:
        return ""
    candidates = " | ".join(
        f"pid={window.process_id} handle={window.handle:#x} class={window.class_name!r} "
        f"title={window.title!r} foreground={window.foreground} monitor={window.monitor_bounds}"
        for window in discovery.windows
    )
    return f"; candidates: {candidates}"


def _errors(discovery: DiscoveryResult) -> str:
    return f" ({'; '.join(discovery.errors)})" if discovery.errors else ""
