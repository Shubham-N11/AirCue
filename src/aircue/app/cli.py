"""Command-line entry point."""

from __future__ import annotations

import argparse
import sys
import time

from aircue.app.runtime import AirCueRuntime
from aircue.config.loader import ConfigError, load_config
from aircue.presentation.classify import classify_target
from aircue.presentation.discovery import DiscoveryResult, PowerPointDiscovery
from aircue.presentation.win32 import CtypesWin32
from aircue.state.machine import StateMachine
from aircue.state.states import InteractionState
from aircue.state.transitions import TransitionTrigger

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

    commands.add_parser(
        "diagnose", help="print PowerPoint window and target diagnostics"
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "run":
        return _run(args.config)
    if args.command == "benchmark":
        return _benchmark(args)
    return _diagnose()


def _run(config_path: str | None) -> int:
    try:
        config = load_config(config_path)
    except ConfigError as exc:
        return _config_failure(exc)

    runtime = AirCueRuntime(config)
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


def _benchmark(args: argparse.Namespace) -> int:
    if args.mode == "replay" and not args.fixture:
        print("aircue: benchmark --mode replay requires --fixture PATH", file=sys.stderr)
        return EXIT_USAGE
    if args.mode == "live" and args.fixture:
        print("aircue: benchmark --mode live does not take --fixture", file=sys.stderr)
        return EXIT_USAGE
    try:
        load_config(args.config)
    except ConfigError as exc:
        return _config_failure(exc)
    print(
        f"aircue: benchmark mode {args.mode!r} is not available in this build",
        file=sys.stderr,
    )
    return EXIT_UNAVAILABLE


def _diagnose(discovery: DiscoveryResult | None = None) -> int:
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
