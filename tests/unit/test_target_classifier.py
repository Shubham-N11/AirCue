from __future__ import annotations

from aircue.presentation.classify import (
    EDITOR_CLASS,
    SLIDESHOW_CLASS,
    classify_target,
)
from aircue.presentation.discovery import DiscoveryResult, ProcessInfo, WindowCandidate
from aircue.presentation.target import ScreenRect, TargetKind, capabilities_for

PID = 100
PRIMARY = ScreenRect(0, 0, 1920, 1080)
SECONDARY = ScreenRect(1920, 0, 3840, 1080)
THIRD = ScreenRect(3840, 0, 5760, 1080)


def window(
    handle: int,
    *,
    process_id: int = PID,
    class_name: str = SLIDESHOW_CLASS,
    title: str = "Deck",
    visible: bool = True,
    foreground: bool = False,
    window_bounds: ScreenRect = PRIMARY,
    monitor_bounds: ScreenRect = PRIMARY,
) -> WindowCandidate:
    return WindowCandidate(
        process_id=process_id,
        handle=handle,
        class_name=class_name,
        title=title,
        visible=visible,
        foreground=foreground,
        window_bounds=window_bounds,
        monitor_bounds=monitor_bounds,
    )


def console(handle: int, *, monitor_bounds: ScreenRect = PRIMARY, **overrides) -> WindowCandidate:
    return window(
        handle,
        class_name=EDITOR_CLASS,
        title="Presenter View - Deck",
        monitor_bounds=monitor_bounds,
        **overrides,
    )


def classify(
    *windows: WindowCandidate, process_ids: tuple[int, ...] = (PID,), captured_ns: int = 5
):
    discovery = DiscoveryResult(
        processes=tuple(ProcessInfo(process_id, "POWERPNT.EXE") for process_id in process_ids),
        windows=tuple(windows),
    )
    return classify_target(discovery, captured_ns)


def test_one_foreground_fullscreen_window_is_a_normal_slideshow() -> None:
    output = window(
        1,
        foreground=True,
        title="Quarterly review",
        window_bounds=SECONDARY,
        monitor_bounds=SECONDARY,
    )
    snapshot = classify(output)
    assert snapshot.kind is TargetKind.NORMAL_SLIDESHOW
    assert snapshot.capabilities == capabilities_for(TargetKind.NORMAL_SLIDESHOW)
    assert snapshot.process_id == PID
    assert snapshot.window_handle == 1
    assert snapshot.output_handle is None
    assert snapshot.monitor_bounds == SECONDARY
    assert snapshot.title == "Quarterly review"
    assert snapshot.captured_ns == 5


def test_presenter_console_with_a_paired_output_is_presenter_view() -> None:
    presenter = console(1, foreground=True)
    output = window(2, window_bounds=SECONDARY, monitor_bounds=SECONDARY)
    snapshot = classify(presenter, output)

    assert snapshot.kind is TargetKind.PRESENTER_VIEW
    assert snapshot.capabilities == capabilities_for(TargetKind.PRESENTER_VIEW)
    assert snapshot.window_handle == 1
    assert snapshot.output_handle == 2
    assert snapshot.monitor_bounds == SECONDARY
    assert snapshot.title == "Presenter View - Deck"


def test_foreground_output_with_a_paired_console_is_presenter_view() -> None:
    presenter = console(1)
    output = window(2, foreground=True, window_bounds=SECONDARY, monitor_bounds=SECONDARY)
    snapshot = classify(presenter, output)

    assert snapshot.kind is TargetKind.PRESENTER_VIEW
    assert snapshot.window_handle == 2
    assert snapshot.output_handle is None
    assert snapshot.monitor_bounds == SECONDARY


def test_foreground_editor_without_an_output_is_edit_mode() -> None:
    editor = window(
        1,
        class_name=EDITOR_CLASS,
        title="Deck - PowerPoint",
        foreground=True,
        window_bounds=ScreenRect(100, 100, 1500, 900),
    )
    snapshot = classify(editor)
    assert snapshot.kind is TargetKind.EDIT_MODE
    assert snapshot.capabilities == capabilities_for(TargetKind.EDIT_MODE)
    assert snapshot.window_handle == 1
    assert snapshot.monitor_bounds == PRIMARY


def test_no_foreground_powerpoint_window_is_unknown() -> None:
    snapshot = classify(window(1))
    assert snapshot.kind is TargetKind.UNKNOWN
    assert snapshot.window_handle is None
    assert snapshot.captured_ns == 5


def test_no_windows_is_unknown() -> None:
    snapshot = classify()
    assert snapshot.kind is TargetKind.UNKNOWN
    assert snapshot.capabilities == capabilities_for(TargetKind.UNKNOWN)


def test_hidden_foreground_window_is_ignored() -> None:
    snapshot = classify(window(1, visible=False, foreground=True))
    assert snapshot.kind is TargetKind.UNKNOWN


def test_two_fullscreen_outputs_are_ambiguous() -> None:
    first = window(1, foreground=True)
    second = window(2, process_id=101, window_bounds=SECONDARY, monitor_bounds=SECONDARY)
    snapshot = classify(first, second, process_ids=(PID, 101))
    assert snapshot.kind is TargetKind.UNKNOWN


def test_unpaired_presenter_console_is_unknown() -> None:
    snapshot = classify(console(1, foreground=True))
    assert snapshot.kind is TargetKind.UNKNOWN


def test_presenter_output_on_the_console_monitor_is_unknown() -> None:
    presenter = console(1, foreground=True)
    output = window(2)
    snapshot = classify(presenter, output)
    assert snapshot.kind is TargetKind.UNKNOWN


def test_presenter_output_from_another_process_is_unknown() -> None:
    presenter = console(1, foreground=True)
    output = window(2, process_id=101, window_bounds=SECONDARY, monitor_bounds=SECONDARY)
    snapshot = classify(presenter, output, process_ids=(PID, 101))
    assert snapshot.kind is TargetKind.UNKNOWN


def test_multiple_consoles_for_the_output_are_ambiguous() -> None:
    presenter = console(1)
    second = console(3, process_id=PID, monitor_bounds=THIRD)
    output = window(2, foreground=True, window_bounds=SECONDARY, monitor_bounds=SECONDARY)
    snapshot = classify(presenter, second, output)
    assert snapshot.kind is TargetKind.UNKNOWN


def test_unknown_foreground_window_class_is_unknown() -> None:
    snapshot = classify(window(1, class_name="SomeOtherClass", foreground=True))
    assert snapshot.kind is TargetKind.UNKNOWN


def test_a_windowed_slideshow_is_unknown() -> None:
    inset = ScreenRect(100, 100, 1800, 1000)
    snapshot = classify(window(1, foreground=True, window_bounds=inset))
    assert snapshot.kind is TargetKind.UNKNOWN


def test_one_pixel_rounding_still_covers_the_monitor() -> None:
    rounded = ScreenRect(1, 0, 1921, 1080)
    snapshot = classify(window(1, foreground=True, window_bounds=rounded))
    assert snapshot.kind is TargetKind.NORMAL_SLIDESHOW


def test_a_background_editor_does_not_block_a_normal_slideshow() -> None:
    editor = window(9, class_name=EDITOR_CLASS, title="Deck - PowerPoint")
    output = window(1, foreground=True)
    snapshot = classify(editor, output)
    assert snapshot.kind is TargetKind.NORMAL_SLIDESHOW
    assert snapshot.window_handle == 1
