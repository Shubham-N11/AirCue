"""Config-driven gesture recognition for one primary hand per frame."""

from __future__ import annotations

from aircue.config.schema import Config
from aircue.gestures.classifiers import is_fist, is_peace, is_shaka, is_thumbs_up
from aircue.gestures.pinch import PinchGestureRecognizer, PinchState
from aircue.gestures.priority import select_highest
from aircue.gestures.rotation import RotationDetector, RotationDirection, RotationEvent
from aircue.gestures.semantic import (
    GestureAction,
    SemanticEvent,
    SemanticMapper,
)
from aircue.gestures.vocabulary import Gesture
from aircue.state.states import InteractionState
from aircue.vision.types import HandRecord


def static_gesture(hand: HandRecord | None) -> Gesture | None:
    """Return the static pose this hand matches, if any."""
    if hand is None:
        return None
    if is_fist(hand):
        return Gesture.FIST
    if is_thumbs_up(hand):
        return Gesture.THUMBS_UP
    if is_peace(hand):
        return Gesture.PEACE
    if is_shaka(hand):
        return Gesture.SHAKA
    return None


class GestureRecognizer:
    """Emits at most one semantic gesture event per frame.

    All thresholds and windows come from the validated configuration. The
    recognizer never executes presentation actions or synthesizes input.
    """

    def __init__(self, config: Config) -> None:
        self._semantic = SemanticMapper(
            activation_hold_ms=config.timing.activation_hold_ms,
            resume_hold_ms=config.timing.resume_hold_ms,
            fist_confirm_ms=config.timing.fist_confirm_ms,
            peace_confirm_ms=config.timing.peace_confirm_ms,
            shaka_hold_ms=config.timing.shaka_hold_ms,
            gesture_cooldown_ms=config.timing.gesture_cooldown_ms,
            rearm_ms=config.timing.rearm_ms,
            confidence_threshold=config.vision.confidence_threshold,
        )
        self._pinch = PinchGestureRecognizer(
            long_pinch_ms=config.timing.long_pinch_ms,
            close_threshold=config.pinch.close_threshold,
            release_threshold=config.pinch.release_threshold,
            rearm_threshold=config.pinch.rearm_threshold,
            close_confirm_ms=config.pinch.close_confirm_ms,
            release_confirm_ms=config.pinch.release_confirm_ms,
            rearm_confirm_ms=config.pinch.rearm_confirm_ms,
        )
        self._rotation = RotationDetector(
            activation_deg=config.rotation.activation_deg,
            neutral_band_deg=config.rotation.neutral_band_deg,
            continuous_enabled=config.rotation.continuous_enabled,
            repeat_step_deg=config.rotation.repeat_step_deg,
            repeat_interval_ms=config.rotation.repeat_interval_ms,
            max_events_per_second=config.rotation.max_events_per_second,
        )

    @property
    def pinch_closed(self) -> bool:
        """True while the pinch confirmed closed and has not been released."""
        return self._pinch.pinch_state is PinchState.PINCHED

    def reset(self) -> None:
        self._semantic.reset()
        self._pinch.reset()
        self._rotation.reset()

    def update(
        self,
        hand: HandRecord | None,
        state: InteractionState,
        timestamp_ns: int,
        *,
        sequence: int = 0,
    ) -> SemanticEvent | None:
        confidence = 0.0 if hand is None else hand.confidence
        candidates: list[SemanticEvent] = []

        semantic = self._semantic.update(
            static_gesture(hand), confidence, state, timestamp_ns, sequence=sequence
        )
        if semantic is not None:
            candidates.append(semantic)

        pinch = self._pinch.update(hand, state, timestamp_ns, sequence=sequence)
        if pinch is not None:
            candidates.append(pinch)

        rotation = self._rotation.update(hand, timestamp_ns, sequence=sequence)
        if rotation is not None:
            candidates.append(_rotation_event(rotation))

        return select_highest(candidates)


def _rotation_event(event: RotationEvent) -> SemanticEvent:
    if event.direction is RotationDirection.CLOCKWISE:
        gesture = Gesture.OPEN_PALM_CLOCKWISE
        action = GestureAction.NEXT_SLIDE
    else:
        gesture = Gesture.OPEN_PALM_COUNTERCLOCKWISE
        action = GestureAction.PREV_SLIDE
    return SemanticEvent(
        action=action,
        gesture=gesture,
        onset_ns=event.timestamp_ns,
        onset_sequence=event.onset_sequence,
        timestamp_ns=event.timestamp_ns,
        confidence=event.confidence,
    )
