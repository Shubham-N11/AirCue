from __future__ import annotations

from aircue.presentation.target import TargetKind, capabilities_for
from aircue.state.feedback import StatusModel
from aircue.state.states import InteractionState
from aircue.ui.overlay import format_status

S = InteractionState


def status(
    state: InteractionState,
    kind: TargetKind,
    *,
    prompt: str | None = None,
    reason: str | None = None,
    warning: str | None = None,
) -> StatusModel:
    return StatusModel(
        state=state,
        target_kind=kind,
        capabilities=capabilities_for(kind),
        prompt=prompt,
        reason=reason,
        warning=warning,
    )


def test_idle_shows_target_capabilities_and_the_activation_prompt() -> None:
    text = format_status(
        status(
            S.IDLE,
            TargetKind.NORMAL_SLIDESHOW,
            prompt="Thumbs-up hold 0.8 s or Ctrl+Alt+A to activate",
        )
    )
    assert "IDLE" in text
    assert "normal_slideshow" in text
    assert "navigation, pointer" in text
    assert "Ctrl+Alt+A" in text


def test_paused_shows_the_resume_prompt_and_reason() -> None:
    text = format_status(
        status(
            S.PAUSED,
            TargetKind.NORMAL_SLIDESHOW,
            prompt="Thumbs-up hold 0.25 s to resume",
            reason="focus_loss",
        )
    )
    assert "PAUSED" in text
    assert "0.25" in text
    assert "reason: focus_loss" in text


def test_error_shows_the_fault_reason() -> None:
    text = format_status(
        status(S.ERROR, TargetKind.UNKNOWN, reason="camera fault: no frame")
    )
    assert "ERROR" in text
    assert "target: unknown" in text
    assert "capabilities: none" in text
    assert "camera fault" in text


def test_presenter_view_reports_navigation_only() -> None:
    text = format_status(status(S.ACTIVE, TargetKind.PRESENTER_VIEW))
    assert "capabilities: navigation" in text
    assert "pointer" not in text


def test_modes_show_their_name_and_full_capabilities() -> None:
    for state in (S.POINTER_MODE, S.SCROLL_MODE):
        text = format_status(status(state, TargetKind.NORMAL_SLIDESHOW))
        assert state.value.upper() in text
        assert "navigation, pointer" in text


def test_a_resource_warning_is_rendered_on_its_own_line() -> None:
    text = format_status(
        status(
            S.ACTIVE,
            TargetKind.NORMAL_SLIDESHOW,
            warning="resource limit: cpu 95% >= 85%",
        )
    )

    assert "ACTIVE" in text
    assert "warning: resource limit: cpu 95% >= 85%" in text
