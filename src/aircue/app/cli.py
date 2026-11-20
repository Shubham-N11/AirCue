"""Command-line entry point."""

from __future__ import annotations

import argparse
import sys
import time

from aircue.app.runtime import AirCueRuntime
from aircue.config.loader import ConfigError, load_config
from aircue.config.schema import Config
from aircue.diagnostics.session_log import close_session_logging, configure_session_logging
from aircue.hardware.calibration import CalibrationError, ProfileCalibrator
from aircue.hardware.hints import hint_for, probe_evidence
from aircue.hardware.selection import HardwareSelection, select_hardware
from aircue.performance.replay import (
    FrameFixture,
    ReplayError,
    ReplayFixtureError,
    run_replay,
)
from aircue.presentation.classify import classify_target
from aircue.presentation.discovery import DiscoveryResult, PowerPointDiscovery
from aircue.presentation.win32 import CtypesWin32
from aircue.state.machine import StateMachine
from aircue.state.states import InteractionState
from aircue.state.transitions import TransitionTrigger
from aircue.ui.overlay import Win32StatusOverlay
from aircue.vision.tracker import MediaPipeHandTracker
from aircue.vision.types import TrackerError

EXIT_OK = 0
EXIT_STARTUP_FAILED = 1
EXIT_USAGE = 2
EXIT_UNAVAILABLE = 3


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="aircue",
        description="Gesture-based presentation control for Windows.",
    )
    commands = parser.add_subparsers(dest="command", required=True)

    run = commands.add_parser("run", help="start gesture control for a slideshow")
    run.add_argument(
        "--config",
        metavar="PATH",
        help="configuration file (defaults to %%APPDATA%%\\AirCue\\config.json)",
    )

    benchmark = commands.add_parser("benchmark", help="run a performance benchmark")
    benchmark.add_argument("--mode", choices=("replay", "live"), required=True)
    benchmark.add_argument("--fixture", metavar="PATH", help="replay fixture file")
    benchmark.add_argument("--config", metavar="PATH", help="configuration file")

    diagnose = commands.add_parser(
        "diagnose", help="print hardware, PowerPoint window, and target diagnostics"
    )
    diagnose.add_argument("--config", metavar="PATH", help="configuration file")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "run":
        return _run(args.config)
    if args.command == "benchmark":
        return _benchmark(args)
    try:
        config = load_config(args.config)
    except ConfigError as exc:
        return _config_failure(exc)
    return _diagnose(selection=_select_hardware(config, None))


def _run(config_path: str | None) -> int:
    try:
        config = load_config(config_path)
    except ConfigError as exc:
        return _config_failure(exc)

    configure_session_logging(level=config.diagnostics.log_level)
    tracker = _calibration_tracker(config)
    selection = _select_hardware(config, tracker)
    for line in selection.diagnostic_lines():
        print(f"aircue: hardware {line}")
    overlay = (
        Win32StatusOverlay(opacity=config.ui.overlay_opacity)
        if config.ui.overlay_enabled
        else None
    )
    runtime = AirCueRuntime(
        config, tracker=tracker, indicator=overlay, selection=selection
    )
    try:
        record = runtime.initialize()
        if not record.accepted or runtime.state is not InteractionState.IDLE:
            print(f"aircue: startup failed: {record.reason}", file=sys.stderr)
            return EXIT_STARTUP_FAILED
        print(f"aircue: ready (state={runtime.state.value})")
        runtime.run()
        return EXIT_OK
    finally:
        runtime.close()
        if overlay is not None:
            overlay.close()
        close_session_logging()


def _benchmark(args: argparse.Namespace) -> int:
    if args.mode == "replay" and not args.fixture:
        print("aircue: benchmark --mode replay requires --fixture PATH", file=sys.stderr)
        return EXIT_USAGE
    if args.mode == "live" and args.fixture:
        print("aircue: benchmark --mode live does not take --fixture", file=sys.stderr)
        return EXIT_USAGE
    try:
        config = load_config(args.config)
    except ConfigError as exc:
        return _config_failure(exc)
    if args.mode == "live":
        print(
            "aircue: benchmark mode 'live' is not available in this build",
            file=sys.stderr,
        )
        return EXIT_UNAVAILABLE
    try:
        fixture = FrameFixture.load(args.fixture)
    except ReplayFixtureError as exc:
        print(f"aircue: {exc}", file=sys.stderr)
        return EXIT_USAGE
    try:
        tracker = MediaPipeHandTracker(
            config.vision.model_path,
            confidence_threshold=config.vision.confidence_threshold,
            max_hands=config.vision.max_hands,
        )
    except TrackerError as exc:
        print(f"aircue: benchmark tracker unavailable: {exc}", file=sys.stderr)
        return EXIT_STARTUP_FAILED
    try:
        report = run_replay(fixture, config, tracker=tracker)
    except ReplayError as exc:
        print(f"aircue: {exc}", file=sys.stderr)
        return EXIT_STARTUP_FAILED
    print(report.to_json())
    return EXIT_OK


def _calibration_tracker(config: Config) -> MediaPipeHandTracker | None:
    """Load the tracker before startup so the profile can be calibrated once."""
    if config.hardware.profile != "auto" or not config.vision.model_path.strip():
        return None
    try:
        return MediaPipeHandTracker(
            config.vision.model_path,
            confidence_threshold=config.vision.confidence_threshold,
            max_hands=config.vision.max_hands,
        )
    except TrackerError:
        # initialize() reports the tracker failure with the usual startup path.
        return None


def _select_hardware(
    config: Config, tracker: MediaPipeHandTracker | None
) -> HardwareSelection:
    evidence = probe_evidence()
    hint = hint_for(evidence)
    calibration = None
    calibration_error = None
    if config.hardware.profile == "auto" and tracker is not None:
        try:
            calibration = ProfileCalibrator(config.hardware).startup(tracker, hint.tier)
        except CalibrationError as exc:
            calibration_error = str(exc)
    return select_hardware(
        config.hardware,
        evidence=evidence,
        calibration=calibration,
        calibration_error=calibration_error,
    )


def _diagnose(
    discovery: DiscoveryResult | None = None,
    *,
    selection: HardwareSelection | None = None,
) -> int:
    result = discovery if discovery is not None else PowerPointDiscovery(CtypesWin32()).discover()
    snapshot = classify_target(result, time.monotonic_ns())

    if not result.available:
        print("PowerPoint is not running.")
    for error in result.errors:
        print(f"error: {error}")
    for window in result.windows:
        print(
            f"window {window.handle:#x} pid={window.process_id} "
            f"class={window.class_name!r} title={window.title!r} "
            f"visible={window.visible} foreground={window.foreground} "
            f"window={window.window_bounds} monitor={window.monitor_bounds}"
        )
    capabilities = snapshot.capabilities
    print(
        f"target={snapshot.kind.value} "
        f"navigation={capabilities.navigation} pointer={capabilities.pointer}"
    )
    if snapshot.monitor_bounds is not None:
        print(f"target-monitor={snapshot.monitor_bounds}")
    resolved = selection or select_hardware(Config().hardware)
    for line in resolved.diagnostic_lines():
        print(f"hardware {line}")
    return EXIT_OK


def _config_failure(exc: ConfigError) -> int:
    machine = StateMachine()
    record = machine.apply(
        TransitionTrigger.INITIALIZATION_FAILED,
        time.monotonic_ns(),
        reason=f"config: {exc}",
    )
    print(f"aircue: startup failed: {record.reason}", file=sys.stderr)
    return EXIT_USAGE
