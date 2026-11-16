import pytest

from aircue.gestures.priority import priority_rank, select_highest
from aircue.gestures.semantic import GestureAction, SemanticEvent
from aircue.gestures.vocabulary import Gesture


def event(action: GestureAction) -> SemanticEvent:
    return SemanticEvent(action, Gesture.FIST, 0, 0, 0.9)


def test_every_action_has_a_distinct_rank() -> None:
    ranks = [priority_rank(action) for action in GestureAction]
    assert len(set(ranks)) == len(ranks)


def test_empty_candidates_return_none() -> None:
    assert select_highest([]) is None


def test_exit_beats_anything() -> None:
    candidates = [
        event(GestureAction.POINTER_MOVEMENT),
        event(GestureAction.SCROLL),
        event(GestureAction.CLICK_CANDIDATE),
        event(GestureAction.NEXT_SLIDE),
        event(GestureAction.ENTER_POINTER_MODE),
        event(GestureAction.ACTIVATE),
        event(GestureAction.PAUSE_TRACKING),
        event(GestureAction.EXIT_REQUEST),
    ]
    assert select_highest(candidates).action is GestureAction.EXIT_REQUEST


def test_fist_pause_beats_rotation_navigation() -> None:
    candidates = [event(GestureAction.NEXT_SLIDE), event(GestureAction.PAUSE_TRACKING)]
    assert select_highest(candidates).action is GestureAction.PAUSE_TRACKING

    candidates = [event(GestureAction.PREV_SLIDE), event(GestureAction.PAUSE_TRACKING)]
    assert select_highest(candidates).action is GestureAction.PAUSE_TRACKING


def test_click_candidate_beats_pointer_movement() -> None:
    candidates = [
        event(GestureAction.POINTER_MOVEMENT),
        event(GestureAction.CLICK_CANDIDATE),
    ]
    assert select_highest(candidates).action is GestureAction.CLICK_CANDIDATE


def test_scroll_beats_pointer_movement() -> None:
    candidates = [
        event(GestureAction.POINTER_MOVEMENT),
        event(GestureAction.SCROLL),
    ]
    assert select_highest(candidates).action is GestureAction.SCROLL


def test_contradictory_mode_entries_resolve_deterministically() -> None:
    candidates = [
        event(GestureAction.ENTER_POINTER_MODE),
        event(GestureAction.ENTER_SCROLL_MODE),
    ]
    assert select_highest(candidates).action is GestureAction.ENTER_SCROLL_MODE
    reversed_candidates = list(reversed(candidates))
    assert select_highest(reversed_candidates).action is GestureAction.ENTER_SCROLL_MODE


def test_mode_exit_beats_mode_entry() -> None:
    candidates = [
        event(GestureAction.ENTER_SCROLL_MODE),
        event(GestureAction.EXIT_POINTER_MODE),
    ]
    assert select_highest(candidates).action is GestureAction.EXIT_POINTER_MODE


def test_slide_navigation_beats_click() -> None:
    candidates = [
        event(GestureAction.CLICK_CANDIDATE),
        event(GestureAction.NEXT_SLIDE),
    ]
    assert select_highest(candidates).action is GestureAction.NEXT_SLIDE


def test_click_beats_scroll() -> None:
    candidates = [event(GestureAction.SCROLL), event(GestureAction.CLICK_CANDIDATE)]
    assert select_highest(candidates).action is GestureAction.CLICK_CANDIDATE


def test_pause_beats_resume_or_activation() -> None:
    for action in (GestureAction.RESUME_TRACKING, GestureAction.ACTIVATE):
        assert (
            select_highest([event(action), event(GestureAction.PAUSE_TRACKING)]).action
            is GestureAction.PAUSE_TRACKING
        )


def test_activation_and_resume_order_is_fixed() -> None:
    candidates = [event(GestureAction.ACTIVATE), event(GestureAction.RESUME_TRACKING)]
    assert select_highest(candidates).action is GestureAction.RESUME_TRACKING


@pytest.mark.parametrize(
    ("higher", "lower"),
    [
        (GestureAction.EXIT_REQUEST, GestureAction.PAUSE_TRACKING),
        (GestureAction.PAUSE_TRACKING, GestureAction.RESUME_TRACKING),
        (GestureAction.RESUME_TRACKING, GestureAction.EXIT_SCROLL_MODE),
        (GestureAction.EXIT_SCROLL_MODE, GestureAction.ENTER_SCROLL_MODE),
        (GestureAction.ENTER_SCROLL_MODE, GestureAction.NEXT_SLIDE),
        (GestureAction.NEXT_SLIDE, GestureAction.CLICK_CANDIDATE),
        (GestureAction.CLICK_CANDIDATE, GestureAction.SCROLL),
        (GestureAction.SCROLL, GestureAction.POINTER_MOVEMENT),
    ],
)
def test_adjacent_priority_pairs(
    higher: GestureAction, lower: GestureAction
) -> None:
    assert priority_rank(higher) < priority_rank(lower)
    assert select_highest([event(lower), event(higher)]).action is higher


def test_single_candidate_is_returned() -> None:
    candidate = event(GestureAction.SCROLL)
    assert select_highest([candidate]) is candidate
