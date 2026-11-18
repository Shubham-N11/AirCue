import json
from pathlib import Path

import pytest

from aircue.config import Config, ConfigError, load_config, parse_config


def test_design_defaults_are_represented() -> None:
    config = Config()
    assert config.timing.activation_hold_ms == 800
    assert config.timing.resume_hold_ms == 250
    assert config.hotkeys.activate == "ctrl+alt+a"
    assert config.hotkeys.deactivate == "ctrl+alt+d"
    assert config.hotkeys.exit == "ctrl+alt+q"
    assert config.timing.fist_confirm_ms == 200
    assert config.timing.peace_confirm_ms == 250
    assert config.timing.shaka_hold_ms == 1500
    assert config.timing.gesture_cooldown_ms == 500
    assert config.timing.rearm_ms == 300
    assert config.rotation.activation_deg == 25.0
    assert config.rotation.neutral_band_deg == 8.0
    assert config.rotation.continuous_enabled is False
    assert config.rotation.repeat_step_deg == 30.0
    assert config.rotation.repeat_interval_ms == 400
    assert config.rotation.max_events_per_second == 2.0
    assert config.pinch.close_threshold == 0.22
    assert config.pinch.release_threshold == 0.32
    assert config.pinch.rearm_threshold == 0.40
    assert config.pinch.close_confirm_ms == 100
    assert config.pinch.release_confirm_ms == 100
    assert config.pinch.rearm_confirm_ms == 300
    assert config.timing.long_pinch_ms == 700
    assert config.timing.double_click_window_ms == 350
    assert config.pointer.dead_zone == 0.01
    assert config.pointer.smoothing_min_alpha == 0.20
    assert config.pointer.smoothing_max_alpha == 0.45
    assert config.pointer.max_added_latency_ms == 40
    assert config.scroll.dead_zone == 0.05
    assert config.scroll.max_notches_per_second == 10.0
    assert config.timing.tracking_freeze_ms == 300
    assert config.timing.tracking_idle_ms == 1000
    assert config.timing.primary_hand_switch_ms == 500
    assert config.timing.camera_freeze_ms == 2000
    assert config.camera.reconnect_attempts == 3
    assert config.camera.reconnect_backoff_ms == 500
    assert config.timing.target_refresh_ms == 250
    assert config.timing.target_stale_ms == 1000
    assert config.dispatch.pointer_ttl_ms == 100
    assert config.dispatch.scroll_ttl_ms == 150
    assert config.dispatch.click_ttl_ms == 250
    assert config.dispatch.navigation_ttl_ms == 500
    assert config.timing.adapter_deadline_ms == 150
    assert config.timing.adapter_unresponsive_ms == 300
    assert config.timing.metrics_window_s == 10.0
    assert config.timing.benchmark_warmup_s == 10.0
    assert config.timing.benchmark_measure_s == 60.0
    assert config.timing.instrumentation_blocks == 5
    assert config.timing.instrumentation_block_s == 60.0


def test_profile_and_override_fields_exist() -> None:
    config = Config()
    assert config.hardware.profile == "auto"
    assert config.hardware.backend == "auto"
    assert config.hardware.processing_fps == 0.0
    assert (config.hardware.tier1.width, config.hardware.tier1.height) == (640, 360)
    assert (config.hardware.tier2.width, config.hardware.tier2.height) == (1280, 720)
    assert config.hardware.tier1.max_fps == 15.0
    assert config.hardware.tier2.max_fps == 30.0


def test_valid_overrides_are_applied() -> None:
    config = parse_config(
        {
            "timing": {"activation_hold_ms": 900},
            "hotkeys": {"exit": "ctrl+shift+q"},
            "hardware": {"profile": "tier2", "backend": "cpu", "processing_fps": 24},
            "camera": {"device_index": 1},
        }
    )
    assert config.timing.activation_hold_ms == 900
    assert config.hotkeys.exit == "ctrl+shift+q"
    assert config.hardware.profile == "tier2"
    assert config.hardware.processing_fps == 24.0
    assert config.camera.device_index == 1
    assert config.timing.resume_hold_ms == 250


@pytest.mark.parametrize(
    "payload",
    [
        {"timing": {"activation_hold_ms": 0}},
        {"pointer": {"dead_zone": 1.5}},
        {"vision": {"confidence_threshold": -0.1}},
        {"hardware": {"tier2": {"max_fps": 1}}},
    ],
)
def test_out_of_range_values_are_rejected(payload: dict[str, object]) -> None:
    with pytest.raises(ConfigError, match="must be"):
        parse_config(payload)


@pytest.mark.parametrize(
    "payload",
    [
        {"timing": {"activation_hold_ms": "fast"}},
        {"timing": {"activation_hold_ms": True}},
        {"pointer": {"dead_zone": "small"}},
        {"ui": {"overlay_enabled": "yes"}},
        {"hotkeys": {"activate": 42}},
    ],
)
def test_wrong_types_are_rejected(payload: dict[str, object]) -> None:
    with pytest.raises(ConfigError, match="must be"):
        parse_config(payload)


def test_unknown_keys_are_rejected() -> None:
    with pytest.raises(ConfigError, match="unknown key"):
        parse_config({"timing": {"not_a_setting": 1}})
    with pytest.raises(ConfigError, match="unknown key"):
        parse_config({"not_a_section": {}})


def test_invalid_choice_is_rejected() -> None:
    with pytest.raises(ConfigError, match="one of"):
        parse_config({"hardware": {"profile": "tier9"}})


def test_pinch_threshold_ordering_is_enforced() -> None:
    with pytest.raises(ConfigError, match="close < release < rearm"):
        parse_config(
            {"pinch": {"close_threshold": 0.35, "release_threshold": 0.30, "rearm_threshold": 0.40}}
        )


@pytest.mark.parametrize("spec", ["", "ctrl+alt", "hyper+a", "ctrl+a+b"])
def test_invalid_hotkey_is_rejected(spec: str) -> None:
    with pytest.raises(ConfigError, match="hotkeys.activate"):
        parse_config({"hotkeys": {"activate": spec}})


def test_load_explicit_file(tmp_path: Path) -> None:
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps({"timing": {"resume_hold_ms": 300}}), encoding="utf-8")
    assert load_config(config_path).timing.resume_hold_ms == 300


def test_load_missing_explicit_file_is_an_error(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="not found"):
        load_config(tmp_path / "absent.json")


def test_load_uses_defaults_when_default_file_absent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("APPDATA", str(tmp_path))
    assert load_config().timing.activation_hold_ms == 800


def test_invalid_json_is_reported(tmp_path: Path) -> None:
    config_path = tmp_path / "config.json"
    config_path.write_text("{", encoding="utf-8")
    with pytest.raises(ConfigError, match="invalid JSON"):
        load_config(config_path)
