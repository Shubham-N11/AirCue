"""JSONL session logging: correlation fields, rotation, and fallback."""

from __future__ import annotations

import json
import logging
import pathlib

import pytest

from aircue.diagnostics.session_log import (
    close_session_logging,
    configure_session_logging,
    default_log_dir,
    record_event,
)


@pytest.fixture(autouse=True)
def _clean_logging():
    yield
    close_session_logging()


def read(path: pathlib.Path) -> list[dict]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line
    ]


def test_records_carry_the_session_generation_and_severity(tmp_path) -> None:
    path = configure_session_logging(tmp_path, session_id="session-1")
    assert path is not None

    record_event("gesture", generation=4, action="next_slide", confidence=0.9)
    close_session_logging()

    payload = read(path)[0]
    assert payload["session"] == "session-1"
    assert payload["generation"] == 4
    assert payload["event"] == "gesture"
    assert payload["severity"] == "info"
    assert payload["action"] == "next_slide"
    assert payload["confidence"] == 0.9
    assert isinstance(payload["ts_ns"], int)


def test_fault_records_carry_their_reason_and_severity(tmp_path) -> None:
    path = configure_session_logging(tmp_path, session_id="session-2")
    assert path is not None

    record_event(
        "fault", generation=7, level=logging.ERROR, reason="camera read failed"
    )
    close_session_logging()

    payload = read(path)[0]
    assert payload["session"] == "session-2"
    assert payload["generation"] == 7
    assert payload["event"] == "fault"
    assert payload["severity"] == "error"
    assert payload["reason"] == "camera read failed"


def test_existing_logger_calls_become_json_lines(tmp_path) -> None:
    path = configure_session_logging(tmp_path, session_id="session-3")
    assert path is not None

    logging.getLogger("aircue.runtime").warning("camera read failed: busy")
    close_session_logging()

    payload = read(path)[0]
    assert payload["session"] == "session-3"
    assert payload["event"] == "log"
    assert payload["message"] == "camera read failed: busy"
    assert payload["severity"] == "warning"


def test_large_sessions_rotate_into_a_backup(tmp_path) -> None:
    path = configure_session_logging(
        tmp_path, session_id="session-4", max_bytes=250, backup_count=1
    )
    assert path is not None

    for generation in range(10):
        record_event("state", generation=generation, detail="x" * 80)
    close_session_logging()

    assert (tmp_path / "aircue.jsonl.1").exists()
    assert all(payload["event"] == "state" for payload in read(path))
    assert all(
        payload["event"] == "state" for payload in read(tmp_path / "aircue.jsonl.1")
    )


def test_an_unwritable_log_directory_falls_back_to_stderr(
    tmp_path, monkeypatch, capsys
) -> None:
    def deny(self, *args, **kwargs):
        raise OSError("denied")

    monkeypatch.setattr(pathlib.Path, "mkdir", deny)
    assert configure_session_logging(tmp_path, session_id="session-5") is None

    record_event("state", generation=1)
    close_session_logging()

    assert '"event":"state"' in capsys.readouterr().err


def test_default_log_dir_follows_localappdata(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    assert default_log_dir() == tmp_path / "AirCue" / "logs"
