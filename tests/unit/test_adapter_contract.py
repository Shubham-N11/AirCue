from __future__ import annotations

import ast
from pathlib import Path

import pytest

from aircue.commands.commands import Command
from aircue.presentation.adapter import (
    AdapterError,
    AdapterResult,
    Click,
    CommandPayload,
    DoubleClick,
    Navigate,
    PointerMove,
    PresentationAdapter,
    Scroll,
    SlideDirection,
)
from aircue.presentation.target import (
    MonitorBounds,
    TargetCapabilities,
    TargetKind,
    TargetSnapshot,
    capabilities_for,
)

SNAPSHOT = TargetSnapshot(captured_ns=1)
PAYLOAD_TYPES = (Navigate, PointerMove, Click, DoubleClick, Scroll)


class FakeAdapter:
    def __init__(self) -> None:
        self.executed: list[CommandPayload] = []

    def snapshot(self) -> TargetSnapshot:
        return SNAPSHOT

    def refresh(self) -> TargetSnapshot:
        return SNAPSHOT

    def execute(self, payload: CommandPayload) -> AdapterResult:
        self.executed.append(payload)
        return AdapterResult()


def test_a_fake_adapter_satisfies_the_protocol() -> None:
    subject = FakeAdapter()
    assert isinstance(subject, PresentationAdapter)
    assert subject.snapshot() == SNAPSHOT
    assert subject.execute(Navigate(SlideDirection.NEXT)) == AdapterResult()
    assert subject.executed == [Navigate(SlideDirection.NEXT)]


def test_raw_commands_are_not_adapter_payloads() -> None:
    # The adapter accepts only payloads built after command gating.
    for command in Command:
        assert not isinstance(command, PAYLOAD_TYPES)


def test_a_result_without_an_error_is_a_success() -> None:
    result = AdapterResult()
    assert result.ok is True
    assert result.error is None


def test_a_result_with_an_error_sent_no_input() -> None:
    result = AdapterResult(AdapterError.FOCUS_LOST, "foreground changed")
    assert result.ok is False
    assert result.error is AdapterError.FOCUS_LOST
    assert result.detail == "foreground changed"


def test_error_codes_cover_every_specified_failure() -> None:
    assert set(AdapterError) == {
        AdapterError.FOCUS_LOST,
        AdapterError.TARGET_CHANGED,
        AdapterError.TARGET_UNAVAILABLE,
        AdapterError.UNSUPPORTED_PRESENTER_VIEW,
        AdapterError.STALE_COMMAND,
        AdapterError.INPUT_BLOCKED,
        AdapterError.ADAPTER_UNAVAILABLE,
        AdapterError.TIMEOUT,
        AdapterError.INTERNAL,
    }


def test_unknown_snapshot_defaults_are_fail_closed() -> None:
    snapshot = TargetSnapshot(captured_ns=5)
    assert snapshot.kind is TargetKind.UNKNOWN
    assert snapshot.capabilities == capabilities_for(TargetKind.UNKNOWN)
    assert snapshot.process_id is None
    assert snapshot.window_handle is None
    assert snapshot.output_handle is None
    assert snapshot.monitor_bounds is None
    assert snapshot.title is None


@pytest.mark.parametrize("kind", list(TargetKind))
def test_snapshot_capabilities_must_match_the_target_kind(kind: TargetKind) -> None:
    accepted = TargetSnapshot(captured_ns=0, kind=kind, capabilities=capabilities_for(kind))
    assert accepted.capabilities == capabilities_for(kind)

    wrong = (
        TargetCapabilities()
        if kind is TargetKind.NORMAL_SLIDESHOW
        else TargetCapabilities(navigation=True, pointer=True)
    )
    with pytest.raises(ValueError):
        TargetSnapshot(captured_ns=0, kind=kind, capabilities=wrong)


def test_snapshot_records_handles_bounds_and_title() -> None:
    bounds = MonitorBounds(left=1920, top=0, right=3840, bottom=1080)
    snapshot = TargetSnapshot(
        captured_ns=10,
        kind=TargetKind.PRESENTER_VIEW,
        capabilities=capabilities_for(TargetKind.PRESENTER_VIEW),
        process_id=1234,
        window_handle=11,
        output_handle=22,
        monitor_bounds=bounds,
        title="Quarterly review",
    )
    assert snapshot.window_handle == 11
    assert snapshot.output_handle == 22
    assert snapshot.monitor_bounds == bounds
    assert snapshot.title == "Quarterly review"


FORBIDDEN_IMPORTS = {
    "ctypes",
    "comtypes",
    "pythoncom",
    "pywintypes",
    "win32api",
    "win32com",
    "win32con",
    "win32gui",
    "win32process",
}


def _import_roots(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            roots.add(node.module.split(".")[0])
    return roots


def test_domain_layer_imports_no_win32_or_powerpoint_code() -> None:
    source = Path(__file__).resolve().parents[2] / "src" / "aircue"
    paths = [
        source / "presentation" / "adapter.py",
        source / "presentation" / "target.py",
        *sorted((source / "state").glob("*.py")),
        *sorted((source / "commands").glob("*.py")),
        *sorted((source / "gestures").glob("*.py")),
    ]
    offenders = {
        path.relative_to(source).as_posix(): sorted(_import_roots(path) & FORBIDDEN_IMPORTS)
        for path in paths
    }
    assert {path: found for path, found in offenders.items() if found} == {}
