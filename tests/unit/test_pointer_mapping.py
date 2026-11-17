from __future__ import annotations

import pytest

from aircue.commands.pointer import map_pointer
from aircue.presentation.target import ScreenRect

HD = ScreenRect(0, 0, 1280, 720)
FULL_HD = ScreenRect(0, 0, 1920, 1080)
SECONDARY = ScreenRect(1920, 0, 3840, 1080)


@pytest.mark.parametrize("monitor,center", [(HD, (640, 360)), (FULL_HD, (960, 540))])
def test_neutral_maps_to_the_monitor_center(
    monitor: ScreenRect, center: tuple[int, int]
) -> None:
    assert map_pointer(0.5, 0.5, monitor) == center


def test_a_normalized_position_keeps_its_proportional_place_across_resolutions() -> None:
    hd = map_pointer(0.6, 0.6, HD)
    full_hd = map_pointer(0.6, 0.6, FULL_HD)

    assert hd == (960, 540)
    assert full_hd == (1440, 810)
    assert hd is not None and full_hd is not None
    assert hd[0] / HD.right == pytest.approx(full_hd[0] / FULL_HD.right)
    assert hd[1] / HD.bottom == pytest.approx(full_hd[1] / FULL_HD.bottom)


def test_a_secondary_slideshow_maps_to_its_own_bounds() -> None:
    assert map_pointer(0.5, 0.5, SECONDARY) == (2880, 540)
    assert map_pointer(0.6, 0.4, SECONDARY) == (3360, 270)


def test_small_movement_inside_the_neutral_region_holds_the_center() -> None:
    assert map_pointer(0.505, 0.495, FULL_HD) == (960, 540)


def test_the_active_range_edges_map_to_the_monitor_edges() -> None:
    # active_range 0.4 is centered on 0.5, so 0.3 and 0.7 reach the edges.
    assert map_pointer(0.3, 0.5, FULL_HD) == (0, 540)
    assert map_pointer(0.7, 0.5, FULL_HD) == (1919, 540)
    assert map_pointer(0.5, 0.3, FULL_HD) == (960, 0)
    assert map_pointer(0.5, 0.7, FULL_HD) == (960, 1079)


def test_out_of_range_coordinates_clamp_inside_the_monitor() -> None:
    assert map_pointer(-2.0, 3.0, FULL_HD) == (0, 1079)
    assert map_pointer(2.0, -3.0, SECONDARY) == (3839, 0)


def test_sensitivity_reaches_the_edges_sooner() -> None:
    assert map_pointer(0.6, 0.5, FULL_HD, sensitivity=1.0) == (1440, 540)
    assert map_pointer(0.6, 0.5, FULL_HD, sensitivity=2.0) == (1919, 540)


def test_a_custom_neutral_and_active_range_are_honored() -> None:
    assert map_pointer(0.25, 0.75, HD, neutral_x=0.25, neutral_y=0.75) == (640, 360)
    assert map_pointer(0.45, 0.75, HD, neutral_x=0.25, neutral_y=0.75) == (1279, 360)


def test_an_unidentified_or_empty_monitor_emits_no_position() -> None:
    assert map_pointer(0.5, 0.5, None) is None
    assert map_pointer(0.5, 0.5, ScreenRect(10, 10, 10, 20)) is None
    assert map_pointer(0.5, 0.5, ScreenRect(10, 10, 20, 10)) is None
