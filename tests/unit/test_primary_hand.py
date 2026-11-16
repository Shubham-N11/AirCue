from aircue.vision.primary import PrimaryHandSelector
from aircue.vision.types import WRIST
from tests.fixtures.landmarks import make_observation


def observation(
    x: float, y: float, confidence: float = 0.9, handedness: str = "Right", track_id: int = 0
):
    return make_observation(
        {WRIST: (x, y, 0.0, confidence)},
        confidence=confidence,
        handedness=handedness,
        track_id=track_id,
    )


def selector() -> PrimaryHandSelector:
    return PrimaryHandSelector(switch_window_ms=500, match_distance=0.35)


def test_initial_selection_uses_highest_confidence() -> None:
    chosen = selector().update(
        (observation(0.3, 0.7, 0.8, "Left"), observation(0.7, 0.7, 0.95, "Right")),
        0,
    )
    assert chosen.observation is not None
    assert chosen.observation.handedness == "Right"
    assert chosen.stable_id == 0
    assert chosen.suppress_recognition is False


def test_primary_identity_is_preserved_across_small_movement() -> None:
    source = selector()
    first = source.update((observation(0.40, 0.70),), 0)
    second = source.update((observation(0.45, 0.72),), 33_000_000)
    assert second.stable_id == first.stable_id == 0
    assert second.suppress_recognition is False


def test_higher_confidence_second_hand_does_not_steal_primary() -> None:
    source = selector()
    source.update((observation(0.4, 0.7, 0.8, "Right"), observation(0.7, 0.7, 0.6, "Left")), 0)
    engaged = source.update(
        (observation(0.4, 0.7, 0.55, "Right"), observation(0.7, 0.7, 0.99, "Left")),
        1_500_000_000,
    )
    assert engaged.observation is not None
    assert engaged.observation.handedness == "Right"
    assert engaged.stable_id == 0
    assert engaged.switched is False


def test_primary_loss_waits_for_switch_window() -> None:
    source = selector()
    source.update((observation(0.4, 0.7), observation(0.7, 0.7, 0.8, "Left")), 0)

    before = source.update((observation(0.7, 0.7, 0.8, "Left"),), 499_000_000)
    assert before.observation is None
    assert before.stable_id == 0
    assert before.suppress_recognition is True

    after = source.update((observation(0.7, 0.7, 0.8, "Left"),), 500_000_000)
    assert after.observation is not None
    assert after.observation.handedness == "Left"
    assert after.switched is True
    assert after.stable_id == 1
    assert after.suppress_recognition is True


def test_reacquisition_within_window_keeps_identity_and_suppresses_gap() -> None:
    source = selector()
    source.update((observation(0.4, 0.7),), 0)
    missing = source.update((), 1_000_000_000)
    assert missing.observation is None

    returned = source.update((observation(0.42, 0.71),), 1_200_000_000)
    assert returned.observation is not None
    assert returned.stable_id == 0
    assert returned.suppress_recognition is True

    settled = source.update((observation(0.42, 0.71),), 1_233_000_000)
    assert settled.suppress_recognition is False


def test_no_hands_yields_no_selection() -> None:
    source = selector()
    selection = source.update((), 0)
    assert selection.observation is None
    assert selection.stable_id is None
    assert selection.suppress_recognition is True


def test_distant_hand_is_not_matched_as_primary() -> None:
    source = selector()
    source.update((observation(0.1, 0.1),), 0)
    distant = source.update((observation(0.9, 0.9),), 10_000_000)
    assert distant.observation is None
    assert distant.stable_id == 0
