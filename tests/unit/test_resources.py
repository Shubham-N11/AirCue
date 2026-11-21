from __future__ import annotations

import pytest

from aircue.performance import resources
from aircue.performance.resources import ProcessResourceSampler


class FakeClock:
    def __init__(self) -> None:
        self.now_ns = 0

    def __call__(self) -> int:
        return self.now_ns


class FakeWin32:
    def __init__(self) -> None:
        self.cpu_ns = 0
        self.memory = 64 * 1024 * 1024

    def cpu_time_ns(self) -> int:
        return self.cpu_ns

    def memory_bytes(self) -> int:
        return self.memory


def test_first_sample_has_no_cpu_baseline(monkeypatch) -> None:
    clock = FakeClock()
    monkeypatch.setattr(resources.sys, "platform", "win32")
    monkeypatch.setattr(resources, "_Win32Process", FakeWin32)

    sample = ProcessResourceSampler(clock_ns=clock, cpu_count=4).sample()

    assert sample.cpu_fraction is None
    assert sample.memory_bytes == 64 * 1024 * 1024


def test_cpu_is_a_fraction_of_total_capacity(monkeypatch) -> None:
    clock = FakeClock()
    fake = FakeWin32()
    monkeypatch.setattr(resources.sys, "platform", "win32")
    monkeypatch.setattr(resources, "_Win32Process", lambda: fake)
    sampler = ProcessResourceSampler(clock_ns=clock, cpu_count=4)
    sampler.sample()

    fake.cpu_ns = 500_000_000
    clock.now_ns = 1_000_000_000
    sample = sampler.sample()

    assert sample.cpu_fraction == pytest.approx(0.125)


def test_cpu_fraction_is_clamped(monkeypatch) -> None:
    clock = FakeClock()
    fake = FakeWin32()
    monkeypatch.setattr(resources.sys, "platform", "win32")
    monkeypatch.setattr(resources, "_Win32Process", lambda: fake)
    sampler = ProcessResourceSampler(clock_ns=clock, cpu_count=1)
    sampler.sample()

    fake.cpu_ns = 2_000_000_000
    clock.now_ns = 1_000_000_000
    sample = sampler.sample()

    assert sample.cpu_fraction == 1.0


def test_unavailable_counters_leave_fields_unknown(monkeypatch) -> None:
    def unavailable() -> FakeWin32:
        raise OSError("not available")

    monkeypatch.setattr(resources.sys, "platform", "win32")
    monkeypatch.setattr(resources, "_Win32Process", unavailable)

    sample = ProcessResourceSampler(clock_ns=FakeClock()).sample()

    assert sample.cpu_fraction is None
    assert sample.memory_bytes is None
