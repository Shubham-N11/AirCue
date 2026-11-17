"""Classify discovered PowerPoint windows into the D5 target kinds."""

from __future__ import annotations

from aircue.presentation.discovery import DiscoveryResult, WindowCandidate
from aircue.presentation.target import (
    TargetKind,
    TargetSnapshot,
    capabilities_for,
)

SLIDESHOW_CLASS = "screenClass"
EDITOR_CLASS = "PPTFrameClass"
PRESENTER_TITLE_MARKER = "presenter view"
FULLSCREEN_TOLERANCE_PX = 1


def classify_target(discovery: DiscoveryResult, captured_ns: int) -> TargetSnapshot:
    """Return the only target that the discovered windows support.

    Anything ambiguous, unpaired, hidden, or shaped unlike a slideshow fails
    closed as UNKNOWN.
    """
    windows = [window for window in discovery.windows if window.visible]
    foreground = next((window for window in windows if window.foreground), None)
    if foreground is None:
        return _unknown(captured_ns)

    outputs = [window for window in windows if _is_output(window)]
    if len(outputs) > 1:
        return _unknown(captured_ns)

    output = next(
        (window for window in outputs if window.handle == foreground.handle),
        None,
    )
    if output is not None:
        consoles = [
            window
            for window in windows
            if window.process_id == output.process_id and _is_console(window)
        ]
        if not consoles:
            return _normal_slideshow(captured_ns, output)
        if len(consoles) == 1 and _is_paired(consoles[0], output):
            return _presenter_view(captured_ns, output, output)
        return _unknown(captured_ns)

    if _is_console(foreground):
        if len(outputs) == 1 and _is_paired(foreground, outputs[0]):
            return _presenter_view(captured_ns, foreground, outputs[0])
        return _unknown(captured_ns)

    if foreground.class_name == EDITOR_CLASS:
        return _edit_mode(captured_ns, foreground)

    return _unknown(captured_ns)


def _is_output(window: WindowCandidate) -> bool:
    return window.class_name == SLIDESHOW_CLASS and _covers_monitor(window)


def _covers_monitor(window: WindowCandidate) -> bool:
    window_rect = window.window_bounds
    monitor = window.monitor_bounds
    return all(
        abs(window_edge - monitor_edge) <= FULLSCREEN_TOLERANCE_PX
        for window_edge, monitor_edge in (
            (window_rect.left, monitor.left),
            (window_rect.top, monitor.top),
            (window_rect.right, monitor.right),
            (window_rect.bottom, monitor.bottom),
        )
    )


def _is_console(window: WindowCandidate) -> bool:
    return PRESENTER_TITLE_MARKER in window.title.lower()


def _is_paired(console: WindowCandidate, output: WindowCandidate) -> bool:
    return (
        console.process_id == output.process_id
        and console.monitor_bounds != output.monitor_bounds
    )


def _unknown(captured_ns: int) -> TargetSnapshot:
    return TargetSnapshot(captured_ns=captured_ns)


def _normal_slideshow(captured_ns: int, output: WindowCandidate) -> TargetSnapshot:
    return TargetSnapshot(
        captured_ns=captured_ns,
        kind=TargetKind.NORMAL_SLIDESHOW,
        capabilities=capabilities_for(TargetKind.NORMAL_SLIDESHOW),
        process_id=output.process_id,
        window_handle=output.handle,
        monitor_bounds=output.monitor_bounds,
        title=output.title,
    )


def _presenter_view(
    captured_ns: int, foreground: WindowCandidate, slideshow_output: WindowCandidate
) -> TargetSnapshot:
    return TargetSnapshot(
        captured_ns=captured_ns,
        kind=TargetKind.PRESENTER_VIEW,
        capabilities=capabilities_for(TargetKind.PRESENTER_VIEW),
        process_id=foreground.process_id,
        window_handle=foreground.handle,
        output_handle=(
            slideshow_output.handle if slideshow_output.handle != foreground.handle else None
        ),
        monitor_bounds=slideshow_output.monitor_bounds,
        title=foreground.title,
    )


def _edit_mode(captured_ns: int, foreground: WindowCandidate) -> TargetSnapshot:
    return TargetSnapshot(
        captured_ns=captured_ns,
        kind=TargetKind.EDIT_MODE,
        capabilities=capabilities_for(TargetKind.EDIT_MODE),
        process_id=foreground.process_id,
        window_handle=foreground.handle,
        monitor_bounds=foreground.monitor_bounds,
        title=foreground.title,
    )
