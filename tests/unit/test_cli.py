from __future__ import annotations

from types import SimpleNamespace

import pytest

from aircue.app.cli import EXIT_OK, EXIT_STARTUP_FAILED, EXIT_UNAVAILABLE, EXIT_USAGE, main
from aircue.presentation.discovery import DiscoveryResult, ProcessInfo, WindowCandidate
from aircue.presentation.target import ScreenRect
from aircue.state.states import InteractionState


class FakeRuntime:
    state = InteractionState.IDLE
    record = SimpleNamespace(accepted=True, reason="ready")

    def __init__(self, config, indicator=None) -> None:
        self.config = config
        self.indicator = indicator
        self.closed = False
        self.ran = False

    def initialize(self):
        return self.record

    def run(self) -> None:
        self.ran = True

    def close(self) -> None:
        self.closed = True


@pytest.fixture
def config_file(tmp_path):
    path = tmp_path / "config.json"
    path.write_text("{}", encoding="utf-8")
    return str(path)


@pytest.fixture(autouse=True)
def _no_real_session_log(monkeypatch):
    monkeypatch.setattr("aircue.app.cli.configure_session_logging", lambda **kwargs: None)
    monkeypatch.setattr("aircue.app.cli.close_session_logging", lambda: None)


def test_help_lists_every_subcommand(capsys) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["--help"])
    assert exc.value.code == EXIT_OK
    output = capsys.readouterr().out
    for command in ("run", "benchmark", "diagnose"):
        assert command in output


@pytest.mark.parametrize("command", ["run", "benchmark", "diagnose"])
def test_each_subcommand_has_help(command: str, capsys) -> None:
    with pytest.raises(SystemExit) as exc:
        main([command, "--help"])
    assert exc.value.code == EXIT_OK
    assert command in capsys.readouterr().out


def test_a_missing_configuration_file_is_a_usage_error(tmp_path, capsys) -> None:
    missing = tmp_path / "missing.json"
    assert main(["run", "--config", str(missing)]) == EXIT_USAGE
    assert "config: configuration file not found" in capsys.readouterr().err


def test_invalid_configuration_is_reported_as_a_config_failure(tmp_path, capsys) -> None:
    path = tmp_path / "config.json"
    path.write_text("{not json", encoding="utf-8")
    assert main(["run", "--config", str(path)]) == EXIT_USAGE
    assert "config: " in capsys.readouterr().err


def test_a_successful_start_reports_ready(monkeypatch, config_file, capsys) -> None:
    monkeypatch.setattr("aircue.app.cli.AirCueRuntime", FakeRuntime)
    assert main(["run", "--config", config_file]) == EXIT_OK
    assert "state=idle" in capsys.readouterr().out


def test_a_successful_start_configures_session_logging(
    monkeypatch, config_file
) -> None:
    calls = []
    monkeypatch.setattr("aircue.app.cli.AirCueRuntime", FakeRuntime)
    monkeypatch.setattr(
        "aircue.app.cli.configure_session_logging", lambda **kwargs: calls.append(kwargs)
    )
    assert main(["run", "--config", config_file]) == EXIT_OK
    assert calls == [{"level": "INFO"}]


def test_a_failed_start_reports_the_failing_component(
    monkeypatch, config_file, capsys
) -> None:
    class FailingRuntime(FakeRuntime):
        state = InteractionState.ERROR
        record = SimpleNamespace(accepted=True, reason="camera: busy")

    monkeypatch.setattr("aircue.app.cli.AirCueRuntime", FailingRuntime)
    assert main(["run", "--config", config_file]) == EXIT_STARTUP_FAILED
    assert "startup failed: camera: busy" in capsys.readouterr().err


def test_benchmark_rejects_a_replay_without_a_fixture(capsys) -> None:
    assert main(["benchmark", "--mode", "replay"]) == EXIT_USAGE
    assert "--fixture" in capsys.readouterr().err


def test_benchmark_rejects_a_fixture_in_live_mode(capsys) -> None:
    assert main(["benchmark", "--mode", "live", "--fixture", "f.jsonl"]) == EXIT_USAGE
    assert "does not take --fixture" in capsys.readouterr().err


def test_benchmark_that_is_not_implemented_exits_unavailable(config_file, capsys) -> None:
    args = ["benchmark", "--mode", "replay", "--fixture", "f.jsonl", "--config", config_file]
    assert main(args) == EXIT_UNAVAILABLE
    assert "not available in this build" in capsys.readouterr().err


def test_benchmark_requires_a_mode(capsys) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["benchmark"])
    assert exc.value.code == EXIT_USAGE


def test_diagnose_reports_when_powerpoint_is_not_running(capsys) -> None:
    from aircue.app.cli import _diagnose

    assert _diagnose(DiscoveryResult((), ())) == EXIT_OK
    assert "PowerPoint is not running." in capsys.readouterr().out


def test_diagnose_lists_candidates_and_the_classified_target(capsys) -> None:
    from aircue.app.cli import _diagnose

    monitor = ScreenRect(0, 0, 1920, 1080)
    result = DiscoveryResult(
        processes=(ProcessInfo(4242, "POWERPNT.EXE"),),
        windows=(
            WindowCandidate(
                process_id=4242,
                handle=0x10,
                class_name="screenClass",
                title="Deck",
                visible=True,
                foreground=True,
                window_bounds=monitor,
                monitor_bounds=monitor,
            ),
        ),
    )

    assert _diagnose(result) == EXIT_OK
    output = capsys.readouterr().out
    assert "pid=4242" in output
    assert "class='screenClass'" in output
    assert "title='Deck'" in output
    assert "foreground=True" in output
    assert "monitor=ScreenRect(left=0, top=0, right=1920, bottom=1080)" in output
    assert "target=normal_slideshow" in output
