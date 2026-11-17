from __future__ import annotations

import pytest

from aircue.presentation.target import TargetKind, capabilities_for
from aircue.state.feedback import StatusFeedback, StatusIndicator, StatusModel
from aircue.state.machine import StateMachine
from aircue.state.states import InteractionState
from aircue.state.transitions import TRANSITIONS, TransitionTrigger

S = InteractionState
T = TransitionTrigger


class RecordingIndicator:
    def __init__(self) -> None:
        self.updates: list[StatusModel] = []

    def update(self, status: StatusModel) -> None:
        self.updates.append(status)


def feedback() -> tuple[StatusFeedback, RecordingIndicator]:
    indicator = RecordingIndicator()
    return StatusFeedback(indicator), indicator


def apply(
    subject: StatusFeedback,
    source: InteractionState,
    trigger: TransitionTrigger,
    timestamp_ns: int = 0,
) -> StatusModel:
    return subject.transition(StateMachine(source).apply(trigger, timestamp_ns))


def test_initial_status_is_uninitialized_with_an_unknown_target() -> None:
    subject, indicator = feedback()
    assert subject.status == StatusModel(
        state=S.INITIALIZING,
        target_kind=TargetKind.UNKNOWN,
        capabilities=capabilities_for(TargetKind.UNKNOWN),
    )
    assert indicator.updates == []


def test_reaching_idle_shows_the_activation_prompt() -> None:
    subject, indicator = feedback()
    model = apply(subject, S.INITIALIZING, T.INITIALIZATION_SUCCEEDED)
    assert model.state is S.IDLE
    assert model.prompt is not None
    assert "Ctrl+Alt+A" in model.prompt
    assert "0.8" in model.prompt
    assert model.reason is None
    assert indicator.updates == [model]


def test_reaching_paused_shows_the_resume_prompt_and_the_cause() -> None:
    subject, _ = feedback()
    model = apply(subject, S.ACTIVE, T.FIST_CONFIRMED)
    assert model.state is S.PAUSED
    assert model.prompt is not None
    assert "0.25" in model.prompt
    assert model.reason == T.FIST_CONFIRMED.value


def test_unrecoverable_fault_shows_its_reason_without_a_prompt() -> None:
    subject, _ = feedback()
    model = apply(subject, S.IDLE, T.UNRECOVERABLE_FAULT)
    assert model.state is S.ERROR
    assert model.prompt is None
    assert model.reason == T.UNRECOVERABLE_FAULT.value


def test_leaving_an_attention_state_clears_the_reason_and_prompt() -> None:
    subject, _ = feedback()
    apply(subject, S.ACTIVE, T.FOCUS_LOSS)
    model = apply(subject, S.PAUSED, T.RESUME_CONFIRMED)
    assert model.state is S.ACTIVE
    assert model.prompt is None
    assert model.reason is None


def test_rejected_transition_leaves_status_and_indicator_untouched() -> None:
    subject, indicator = feedback()
    apply(subject, S.INITIALIZING, T.INITIALIZATION_SUCCEEDED)
    before = subject.status
    pushed = len(indicator.updates)

    record = StateMachine(S.IDLE).apply(T.FIST_CONFIRMED, 0)
    model = subject.transition(record)

    assert record.accepted is False
    assert model == before
    assert len(indicator.updates) == pushed


@pytest.mark.parametrize(
    ("source", "trigger", "expected"),
    [
        (
            row.source,
            row.trigger,
            row.target if isinstance(row.target, InteractionState) else S.EXITING,
        )
        for row in TRANSITIONS
    ],
)
def test_every_accepted_transition_updates_the_indicator(
    source: InteractionState,
    trigger: TransitionTrigger,
    expected: InteractionState,
) -> None:
    subject, indicator = feedback()
    record = StateMachine(source).apply(trigger, 0)
    model = subject.transition(record)
    assert record.accepted is True
    assert model.state is expected
    assert indicator.updates[-1] == model


def test_target_change_replaces_kind_and_capabilities() -> None:
    subject, indicator = feedback()
    model = subject.target_changed(TargetKind.NORMAL_SLIDESHOW)
    assert model.target_kind is TargetKind.NORMAL_SLIDESHOW
    assert model.capabilities == capabilities_for(TargetKind.NORMAL_SLIDESHOW)
    assert model.capabilities.navigation and model.capabilities.pointer
    assert indicator.updates[-1] == model


def test_presenter_view_keeps_navigation_and_drops_pointer() -> None:
    subject, _ = feedback()
    model = subject.target_changed(TargetKind.PRESENTER_VIEW)
    assert model.capabilities.navigation is True
    assert model.capabilities.pointer is False


def test_edit_mode_grants_no_capabilities() -> None:
    subject, _ = feedback()
    model = subject.target_changed(TargetKind.EDIT_MODE)
    assert model.capabilities == capabilities_for(TargetKind.EDIT_MODE)


def test_target_change_preserves_state_and_prompt() -> None:
    subject, _ = feedback()
    apply(subject, S.INITIALIZING, T.INITIALIZATION_SUCCEEDED)
    model = subject.target_changed(TargetKind.NORMAL_SLIDESHOW)
    assert model.state is S.IDLE
    assert model.prompt is not None


def test_port_exposes_only_a_status_update() -> None:
    # Schema guard: the indicator must never gain focus-grabbing or input calls.
    members = {
        name
        for name, value in vars(StatusIndicator).items()
        if not name.startswith("_") and callable(value)
    }
    assert members == {"update"}
