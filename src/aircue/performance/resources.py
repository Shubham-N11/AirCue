"""Process CPU and memory sampling for adaptive control and ceilings."""

from __future__ import annotations

import ctypes
import os
import sys
import time
from collections.abc import Callable
from ctypes import wintypes
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class ProcessResources:
    """Process-level use; None means the platform could not measure it."""

    cpu_fraction: float | None = None
    memory_bytes: int | None = None


class ResourceSampler(Protocol):
    def sample(self) -> ProcessResources: ...


class _FileTime(ctypes.Structure):
    _fields_ = [
        ("dwLowDateTime", wintypes.DWORD),
        ("dwHighDateTime", wintypes.DWORD),
    ]

    @property
    def value(self) -> int:
        return (self.dwHighDateTime << 32) | self.dwLowDateTime


class _ProcessMemoryCounters(ctypes.Structure):
    _fields_ = [
        ("cb", wintypes.DWORD),
        ("PageFaultCount", wintypes.DWORD),
        ("PeakWorkingSetSize", ctypes.c_size_t),
        ("WorkingSetSize", ctypes.c_size_t),
        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
        ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
        ("PagefileUsage", ctypes.c_size_t),
        ("PeakPagefileUsage", ctypes.c_size_t),
    ]


class _Win32Process:
    """The two per-process counters needed by the sampler."""

    def __init__(self) -> None:
        self._kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self._psapi = ctypes.WinDLL("psapi", use_last_error=True)
        get_current = self._kernel32.GetCurrentProcess
        get_current.restype = wintypes.HANDLE
        self._handle = get_current()

        get_times = self._kernel32.GetProcessTimes
        get_times.argtypes = [
            wintypes.HANDLE,
            ctypes.POINTER(_FileTime),
            ctypes.POINTER(_FileTime),
            ctypes.POINTER(_FileTime),
            ctypes.POINTER(_FileTime),
        ]
        get_times.restype = wintypes.BOOL
        self._get_times = get_times

        get_memory = self._psapi.GetProcessMemoryInfo
        get_memory.argtypes = [
            wintypes.HANDLE,
            ctypes.POINTER(_ProcessMemoryCounters),
            wintypes.DWORD,
        ]
        get_memory.restype = wintypes.BOOL
        self._get_memory = get_memory

    def cpu_time_ns(self) -> int | None:
        creation = _FileTime()
        exited = _FileTime()
        kernel = _FileTime()
        user = _FileTime()
        try:
            if not self._get_times(
                self._handle,
                ctypes.byref(creation),
                ctypes.byref(exited),
                ctypes.byref(kernel),
                ctypes.byref(user),
            ):
                return None
        except (AttributeError, OSError):
            return None
        return (kernel.value + user.value) * 100

    def memory_bytes(self) -> int | None:
        counters = _ProcessMemoryCounters()
        counters.cb = ctypes.sizeof(_ProcessMemoryCounters)
        try:
            if not self._get_memory(
                self._handle,
                ctypes.byref(counters),
                counters.cb,
            ):
                return None
        except (AttributeError, OSError):
            return None
        return int(counters.WorkingSetSize)


class ProcessResourceSampler:
    """CPU as a fraction of total capacity, memory as working-set bytes."""

    def __init__(
        self,
        *,
        clock_ns: Callable[[], int] = time.monotonic_ns,
        cpu_count: int | None = None,
    ) -> None:
        self._clock_ns = clock_ns
        self._cpu_count = max(
            1, cpu_count if cpu_count is not None else (os.cpu_count() or 1)
        )
        self._last_cpu_ns: int | None = None
        self._last_wall_ns: int | None = None
        self._win32: _Win32Process | None = None
        if sys.platform == "win32":
            try:
                self._win32 = _Win32Process()
            except (AttributeError, OSError):
                self._win32 = None

    def sample(self) -> ProcessResources:
        if self._win32 is None:
            return ProcessResources()
        return ProcessResources(
            cpu_fraction=self._cpu_fraction(self._win32.cpu_time_ns()),
            memory_bytes=self._win32.memory_bytes(),
        )

    def _cpu_fraction(self, cpu_ns: int | None) -> float | None:
        now_ns = self._clock_ns()
        if cpu_ns is None:
            return None
        previous_cpu = self._last_cpu_ns
        previous_wall = self._last_wall_ns
        self._last_cpu_ns = cpu_ns
        self._last_wall_ns = now_ns
        if previous_cpu is None or previous_wall is None:
            return None
        elapsed_ns = now_ns - previous_wall
        used_ns = cpu_ns - previous_cpu
        if elapsed_ns <= 0 or used_ns < 0:
            return None
        return max(0.0, min(1.0, used_ns / elapsed_ns / self._cpu_count))
