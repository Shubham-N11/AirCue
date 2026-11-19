"""JSON configuration loading with type, range, and key validation."""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from dataclasses import fields, is_dataclass
from pathlib import Path
from typing import Any, get_type_hints

from aircue.app.hotkeys import parse_hotkey
from aircue.config.schema import Config


class ConfigError(ValueError):
    """A configuration value or key is invalid."""


def default_config_path() -> Path:
    appdata = os.environ.get("APPDATA")
    base = Path(appdata) if appdata else Path.home() / "AppData" / "Roaming"
    return base / "AirCue" / "config.json"


def load_config(path: str | Path | None = None) -> Config:
    """Load configuration, using defaults when the default file is absent."""
    if path is None:
        config_path = default_config_path()
        if not config_path.exists():
            return Config()
    else:
        config_path = Path(path)
        if not config_path.exists():
            raise ConfigError(f"configuration file not found: {config_path}")
    try:
        with config_path.open("r", encoding="utf-8-sig") as handle:
            raw = json.load(handle)
    except json.JSONDecodeError as exc:
        raise ConfigError(f"{config_path}: invalid JSON: {exc}") from exc
    except OSError as exc:
        raise ConfigError(f"{config_path}: cannot read configuration: {exc}") from exc
    return parse_config(raw, source=str(config_path))


def parse_config(raw: Any, source: str = "<config>") -> Config:
    if not isinstance(raw, dict):
        raise ConfigError(f"{source}: root must be a JSON object")
    config = _construct(Config, raw, source)
    _validate_cross_fields(config, source)
    return config


def _construct(dc_type: type[Any], data: dict[str, Any], source: str) -> Any:
    hints = get_type_hints(dc_type)
    declared = {item.name: item for item in fields(dc_type)}
    unknown = sorted(set(data) - set(declared))
    if unknown:
        raise ConfigError(f"{source}: unknown key(s): {', '.join(unknown)}")

    values: dict[str, Any] = {}
    for name, item in declared.items():
        if name not in data:
            continue
        expected = hints[name]
        path = item.name
        if is_dataclass(expected) and isinstance(expected, type):
            if not isinstance(data[name], dict):
                raise ConfigError(f"{source}: {path} must be an object")
            values[name] = _construct(expected, data[name], source)
            continue
        values[name] = _coerce(data[name], expected, item.metadata, source, path)
    return dc_type(**values)


def _coerce(value: Any, expected: type, metadata: Mapping[str, Any], source: str, path: str) -> Any:
    if expected is bool:
        if not isinstance(value, bool):
            raise ConfigError(f"{source}: {path} must be a boolean")
        return value

    if expected is int:
        if not isinstance(value, int) or isinstance(value, bool):
            raise ConfigError(f"{source}: {path} must be an integer")
        coerced: Any = value
    elif expected is float:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ConfigError(f"{source}: {path} must be a number")
        coerced = float(value)
    elif expected is str:
        if not isinstance(value, str):
            raise ConfigError(f"{source}: {path} must be a string")
        coerced = value
    else:
        raise ConfigError(f"{source}: unsupported configuration type for {path}")

    choices = metadata.get("choices")
    if choices is not None and coerced not in choices:
        raise ConfigError(f"{source}: {path} must be one of {', '.join(choices)}")

    minimum = metadata.get("minimum")
    if minimum is not None and coerced < minimum:
        raise ConfigError(f"{source}: {path} must be >= {minimum}")
    maximum = metadata.get("maximum")
    if maximum is not None and coerced > maximum:
        raise ConfigError(f"{source}: {path} must be <= {maximum}")
    return coerced


def _validate_cross_fields(config: Config, source: str) -> None:
    pinch = config.pinch
    if not pinch.close_threshold < pinch.release_threshold < pinch.rearm_threshold:
        raise ConfigError(f"{source}: pinch thresholds must increase: close < release < rearm")
    pointer = config.pointer
    if pointer.smoothing_min_alpha > pointer.smoothing_max_alpha:
        raise ConfigError(
            f"{source}: pointer.smoothing_min_alpha must be <= pointer.smoothing_max_alpha"
        )
    for tier_name in ("tier1", "tier2", "tier3"):
        tier = getattr(config.hardware, tier_name)
        if tier.min_fps > tier.max_fps:
            raise ConfigError(f"{source}: hardware.{tier_name}.min_fps must be <= max_fps")
    for name in ("activate", "deactivate", "exit"):
        try:
            parse_hotkey(getattr(config.hotkeys, name))
        except ValueError as exc:
            raise ConfigError(f"{source}: hotkeys.{name}: {exc}") from exc
