from __future__ import annotations

import pytest

from aircue.presentation.target import TargetKind, capabilities_for
from aircue.state.activation import (
    ActivationController,
    ActivationRejection,
    ActivationSource,
)
from aircue.state.states import InteractionState
from aircue.state.transitions import TransitionTrigger

S = InteractionState
K = TargetKind
SOURCES = list(ActivationSource)


def controller() -> ActivationController:
    return ActivationController()


def evaluate(
    state: InteractionState,
    kind: TargetKind,
    source: ActivationSource = ActivationSource.GESTURE,
    *,
    target_ready: bool = True,
):
    return controller().evaluate(state, kind, source, target_ready=target_ready)


@pytest.mark.parametrize("source", SOURCES)
def test_idle_activation_accepts_both_deliberate_sources(source: ActivationSource) -> None:
    decision = evaluate(S.IDLE, K.NORMAL_SLIDESHOW, source)
    assert decision.accepted is True
    assert decision.trigger is TransitionTrigger.ACTIVATION_CONFIRMED
    assert decision.source is source
    assert decision.rejection is None


def test_paused_resume_accepts_the_thumbs_up_gesture() -> None:
    decision = evaluate(S.PAUSED, K.NORMAL_SLIDESHOW, ActivationSource.GESTURE)
    assert decision.accepted is True
    assert decision.trigger is TransitionTrigger.RESUME_CONFIRMED


def test_hotkey_cannot_resume_from_paused() -> None:
    decision = evaluate(S.PAUSED, K.NORMAL_SLIDESHOW, ActivationSource.HOTKEY)
    assert decision.accepted is False
    assert decision.rejection is ActivationRejection.HOTKEY_CANNOT_RESUME
    assert decision.trigger is None


@pytest.mark.parametrize("kind", [K.EDIT_MODE, K.UNKNOWN])
@pytest.mark.parametrize("state", [S.IDLE, S.PAUSED])
def test_edit_mode_and_unknown_targets_are_rejected(
    kind: TargetKind, state: InteractionState
) -> None:
    decision = evaluate(state, kind)
    assert decision.accepted is False
    assert decision.rejection is ActivationRejection.TARGET_NOT_ACTIVATABLE


def test_edit_mode_reason_names_the_slideshow_requirement() -> None:
    decision = evaluate(S.IDLE, K.EDIT_MODE)
    assert "slideshow" in decision.reason


def test_unknown_target_reason_names_the_kind() -> None:
    decision = evaluate(S.IDLE, K.UNKNOWN)
    assert "unknown" in decision.reason


@pytest.mark.parametrize("kind", [K.NORMAL_SLIDESHOW, K.PRESENTER_VIEW])
def test_presenter_view_is_activatable(kind: TargetKind) -> None:
    decision = evaluate(S.IDLE, kind)
    assert decision.accepted is True


def test_presenter_view_activation_grants_navigation_only() -> None:
    assert evaluate(S.IDLE, K.PRESENTER_VIEW).accepted is True
    capabilities = capabilities_for(K.PRESENTER_VIEW)
    assert capabilities.navigation is True
    assert capabilities.pointer is False


@pytest.mark.parametrize("kind", list(TargetKind))
def test_unready_target_is_rejected_before_the_kind_check(kind: TargetKind) -> None:
    decision = evaluate(S.IDLE, kind, target_ready=False)
    assert decision.accepted is False
    assert decision.rejection is ActivationRejection.TARGET_NOT_READY


@pytest.mark.parametrize(
    "state",
    [
        S.INITIALIZING,
        S.ACTIVE,
        S.POINTER_MODE,
        S.SCROLL_MODE,
        S.ERROR,
        S.EXITING,
    ],
)
@pytest.mark.parametrize("source", SOURCES)
def test_activation_outside_idle_and_paused_is_rejected(
    state: InteractionState, source: ActivationSource
) -> None:
    decision = evaluate(state, K.NORMAL_SLIDESHOW, source)
    assert decision.accepted is False
    assert decision.rejection is ActivationRejection.NOT_IDLE_OR_PAUSED
    assert decision.trigger is None


def test_every_state_is_covered_by_an_activation_rule() -> None:
    allowed = {S.IDLE, S.PAUSED}
    for state in InteractionState:
        decision = evaluate(state, K.NORMAL_SLIDESHOW)
        assert decision.accepted is (state in allowed)


@pytest.mark.parametrize("kind", list(TargetKind))
@pytest.mark.parametrize("state", [S.IDLE, S.PAUSED])
def test_every_target_kind_has_a_defined_outcome(
    kind: TargetKind, state: InteractionState
) -> None:
    decision = evaluate(state, kind)
    assert decision.accepted is (kind in (K.NORMAL_SLIDESHOW, K.PRESENTER_VIEW))
