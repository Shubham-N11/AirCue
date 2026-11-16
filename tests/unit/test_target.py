from __future__ import annotations

import pytest

from aircue.presentation.target import (
    Capability,
    TargetCapabilities,
    TargetKind,
    capabilities_for,
)

ALL_KINDS = list(TargetKind)


def test_normal_slideshow_supports_navigation_and_pointer() -> None:
    capabilities = capabilities_for(TargetKind.NORMAL_SLIDESHOW)
    assert capabilities.navigation is True
    assert capabilities.pointer is True
    assert capabilities.supports(Capability.NAVIGATION) is True
    assert capabilities.supports(Capability.POINTER) is True


def test_presenter_view_supports_navigation_only() -> None:
    capabilities = capabilities_for(TargetKind.PRESENTER_VIEW)
    assert capabilities.navigation is True
    assert capabilities.pointer is False
    assert capabilities.supports(Capability.NAVIGATION) is True
    assert capabilities.supports(Capability.POINTER) is False


@pytest.mark.parametrize("kind", [TargetKind.EDIT_MODE, TargetKind.UNKNOWN])
def test_edit_mode_and_unknown_support_nothing(kind: TargetKind) -> None:
    capabilities = capabilities_for(kind)
    assert capabilities.navigation is False
    assert capabilities.pointer is False
    assert capabilities.supports(Capability.NAVIGATION) is False
    assert capabilities.supports(Capability.POINTER) is False


def test_every_kind_has_a_capability_record() -> None:
    for kind in ALL_KINDS:
        assert isinstance(capabilities_for(kind), TargetCapabilities)
