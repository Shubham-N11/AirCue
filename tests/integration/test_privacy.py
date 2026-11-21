"""Privacy: frames stay in memory unless debug capture is explicitly enabled."""

from __future__ import annotations

import json
import logging
from dataclasses import replace

import cv2
import pytest

from aircue.config.loader import ConfigError, load_config
from aircue.config.schema import Config
from tests.integration.test_runtime_session import activate, frame, session


def test_frames_are_not_written_without_opt_in(tmp_path) -> None:
    config = replace(
        Config(),
        diagnostics=replace(Config().diagnostics, debug_capture_dir=str(tmp_path)),
    )
    with session(config=config) as (runtime, _adapter, _clock, _tracker):
        activate(runtime, 100)
        for index, milliseconds in enumerate((200, 400, 1_600), start=1):
            runtime.process_frame(frame(milliseconds, index))

    assert list(tmp_path.iterdir()) == []


def test_opted_in_capture_writes_throttled_frames_and_records_the_opt_in(
    tmp_path, caplog: pytest.LogCaptureFixture
) -> None:
    config = replace(
        Config(),
        diagnostics=replace(
            Config().diagnostics,
            debug_capture=True,
            debug_capture_dir=str(tmp_path),
        ),
    )
    with caplog.at_level(logging.INFO, logger="aircue.session"):
        with session(config=config) as (runtime, _adapter, _clock, _tracker):
            activate(runtime, 100)
            for index, milliseconds in enumerate((200, 400, 1_400), start=1):
                runtime.process_frame(frame(milliseconds, index))

    assert [path.name for path in sorted(tmp_path.glob("*.jpg"))] == [
        "frame-1400000000.jpg",
        "frame-200000000.jpg",
    ]
    assert cv2.imread(str(next(tmp_path.glob("*.jpg")))) is not None

    opt_in = [
        record
        for record in caplog.records
        if getattr(record, "event", "") == "privacy"
    ]
    assert len(opt_in) == 1
    assert opt_in[0].fields["directory"] == str(tmp_path)


def test_an_unwritable_capture_directory_disables_capture_without_stopping_the_frame(
    tmp_path, caplog: pytest.LogCaptureFixture
) -> None:
    blocked = tmp_path / "blocked"
    blocked.write_text("not a directory", encoding="utf-8")
    config = replace(
        Config(),
        diagnostics=replace(
            Config().diagnostics,
            debug_capture=True,
            debug_capture_dir=str(blocked),
        ),
    )
    with caplog.at_level(logging.WARNING, logger="aircue.session"):
        with session(config=config) as (runtime, _adapter, _clock, _tracker):
            activate(runtime, 100)
            assert runtime.process_frame(frame(200, 1)) is None
            assert runtime.process_frame(frame(1_400, 2)) is None

    faults = [
        record
        for record in caplog.records
        if getattr(record, "event", "") == "fault"
        and record.fields.get("reason") == "debug capture disabled"
    ]
    assert len(faults) == 1
    assert blocked.is_file()


def test_config_rejects_opt_in_without_a_directory(tmp_path) -> None:
    path = tmp_path / "config.json"
    path.write_text(
        json.dumps({"diagnostics": {"debug_capture": True}}), encoding="utf-8"
    )

    with pytest.raises(ConfigError, match="debug_capture_dir"):
        load_config(path)


def test_a_programmatic_config_without_a_directory_fails_closed(
    caplog: pytest.LogCaptureFixture,
) -> None:
    config = replace(
        Config(),
        diagnostics=replace(Config().diagnostics, debug_capture=True),
    )
    with caplog.at_level(logging.WARNING, logger="aircue.session"):
        with session(config=config) as (runtime, _adapter, _clock, _tracker):
            assert runtime.debug_store is None
            activate(runtime, 100)
            assert runtime.process_frame(frame(200, 1)) is None

    assert any(
        getattr(record, "event", "") == "fault"
        and record.fields.get("reason") == "debug capture disabled"
        for record in caplog.records
    )
