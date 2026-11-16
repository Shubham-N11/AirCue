"""Gesture geometry: user perspective, neutral references, and angle continuity."""

from __future__ import annotations

import math


def to_user_perspective_x(image_x: float) -> float:
    """Mirror a normalized image x coordinate to the user's left-to-right view."""
    return 1.0 - image_x


def to_user_perspective_angle(image_angle_deg: float) -> float:
    """Mirror an image-space wrist angle to the user's view.

    A hand rotating clockwise from the user's perspective produces a positive
    user-perspective angle.
    """
    if not math.isfinite(image_angle_deg):
        raise ValueError("image angle must be finite")
    return -image_angle_deg


def angle_from_neutral(current_deg: float, neutral_deg: float) -> float:
    """Shortest signed rotation from neutral, in [-180, 180)."""
    if not math.isfinite(current_deg) or not math.isfinite(neutral_deg):
        raise ValueError("angles must be finite")
    return (current_deg - neutral_deg + 180.0) % 360.0 - 180.0


def unwrap_angle_deg(previous_unwrapped_deg: float, raw_deg: float) -> float:
    """Shift ``raw_deg`` by whole turns so it stays closest to the previous value."""
    return previous_unwrapped_deg + angle_from_neutral(raw_deg, previous_unwrapped_deg)
