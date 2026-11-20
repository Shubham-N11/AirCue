"""Hardware evidence, tier hints, and the Windows probe (design.md D8).

A tier is an initial hint only. Calibration and benchmarks, not hardware names,
decide the profile and backend that the session actually uses.
"""

from __future__ import annotations

import ctypes
import logging
import os
import struct
import sys
from ctypes import wintypes
from dataclasses import dataclass
from enum import StrEnum

logger = logging.getLogger("aircue.hardware")

_GPU_CLASS_KEY = r"SYSTEM\CurrentControlSet\Control\Class\{4d36e968-e325-11ce-bfc1-08002be10318}"
_CPU_KEY = r"HARDWARE\DESCRIPTION\System\CentralProcessor\0"
_LOW_POWER_CPU_TOKENS = ("celeron", "pentium", "athlon", "atom")


class HardwareTier(StrEnum):
    TIER1 = "tier1"
    TIER2 = "tier2"
    TIER3 = "tier3"


TIER_ORDER: tuple[HardwareTier, ...] = (
    HardwareTier.TIER1,
    HardwareTier.TIER2,
    HardwareTier.TIER3,
)


def previous_tier(tier: HardwareTier) -> HardwareTier | None:
    """The next profile down, or None at Tier 1."""
    index = TIER_ORDER.index(tier)
    return TIER_ORDER[index - 1] if index > 0 else None


def next_tier(tier: HardwareTier) -> HardwareTier | None:
    """The next profile up, or None at Tier 3."""
    index = TIER_ORDER.index(tier)
    return TIER_ORDER[index + 1] if index + 1 < len(TIER_ORDER) else None


@dataclass(frozen=True)
class HardwareEvidence:
    """What the host reports about itself; any field may be unknown."""

    cpu_name: str = ""
    physical_cores: int | None = None
    logical_cores: int | None = None
    ram_gb: float | None = None
    gpu_adapters: tuple[str, ...] = ()

    def describe(self) -> str:
        cores = "unknown" if self.physical_cores is None else str(self.physical_cores)
        logical = "unknown" if self.logical_cores is None else str(self.logical_cores)
        ram = "unknown" if self.ram_gb is None else f"{self.ram_gb:.1f}"
        gpus = ", ".join(self.gpu_adapters) if self.gpu_adapters else "none detected"
        return (
            f"cpu={self.cpu_name or 'unknown'} physical_cores={cores} "
            f"logical_cores={logical} ram_gb={ram} gpus=[{gpus}]"
        )


@dataclass(frozen=True)
class HardwareHint:
    tier: HardwareTier
    evidence: HardwareEvidence
    reason: str


def _is_basic_adapter(name: str) -> bool:
    lowered = name.lower()
    return "basic display" in lowered or "remote display" in lowered


def hint_for(evidence: HardwareEvidence) -> HardwareHint:
    """Classify the evidence into a starting tier; never a final decision."""
    physical = evidence.physical_cores or 0
    ram = evidence.ram_gb or 0.0
    cpu = evidence.cpu_name.lower()

    low_power = next((token for token in _LOW_POWER_CPU_TOKENS if token in cpu), None)
    if low_power is not None:
        return HardwareHint(
            HardwareTier.TIER1, evidence, f"low-power CPU identity ({low_power})"
        )
    if 0 < physical <= 2:
        return HardwareHint(
            HardwareTier.TIER1, evidence, f"{physical} physical cores"
        )
    if 0 < ram < 8.0:
        return HardwareHint(
            HardwareTier.TIER1, evidence, f"{ram:.1f} GB RAM"
        )

    usable_gpus = tuple(
        adapter for adapter in evidence.gpu_adapters if not _is_basic_adapter(adapter)
    )
    if physical >= 8 and ram >= 16.0 and usable_gpus:
        return HardwareHint(
            HardwareTier.TIER3,
            evidence,
            (
                f"{physical} physical cores, {ram:.1f} GB RAM, "
                f"{len(usable_gpus)} GPU adapter(s)"
            ),
        )

    details: list[str] = []
    if physical:
        details.append(f"{physical} physical cores")
    if ram:
        details.append(f"{ram:.1f} GB RAM")
    if not usable_gpus and (physical or ram or cpu):
        details.append("no usable GPU adapter; capped at Tier 2")
    return HardwareHint(
        HardwareTier.TIER2,
        evidence,
        ", ".join(details) if details else "baseline hint (evidence unavailable)",
    )


class _MemoryStatusEx(ctypes.Structure):
    _fields_ = [
        ("dwLength", wintypes.DWORD),
        ("dwMemoryLoad", wintypes.DWORD),
        ("ullTotalPhys", ctypes.c_ulonglong),
        ("ullAvailPhys", ctypes.c_ulonglong),
        ("ullTotalPageFile", ctypes.c_ulonglong),
        ("ullAvailPageFile", ctypes.c_ulonglong),
        ("ullTotalVirtual", ctypes.c_ulonglong),
        ("ullAvailVirtual", ctypes.c_ulonglong),
        ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
    ]


def _cpu_name() -> str:
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, _CPU_KEY) as key:
            value, _ = winreg.QueryValueEx(key, "ProcessorNameString")
        return str(value).strip()
    except (ImportError, OSError) as exc:
        logger.debug("CPU identity unavailable: %s", exc)
        return ""


def _physical_cores() -> int | None:
    try:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        function = kernel32.GetLogicalProcessorInformationEx
        function.argtypes = [
            wintypes.DWORD,
            ctypes.c_void_p,
            ctypes.POINTER(wintypes.DWORD),
        ]
        function.restype = wintypes.BOOL
        length = wintypes.DWORD(0)
        function(0, None, ctypes.byref(length))
        if length.value == 0:
            return None
        buffer = ctypes.create_string_buffer(length.value)
        if not function(
            0, ctypes.cast(buffer, ctypes.c_void_p), ctypes.byref(length)
        ):
            return None
        data = buffer.raw[: length.value]
        count = 0
        offset = 0
        while offset + 8 <= len(data):
            relationship, size = struct.unpack_from("<II", data, offset)
            if size < 8:
                break
            if relationship == 0:  # RelationProcessorCore
                count += 1
            offset += size
        return count or None
    except (AttributeError, OSError, ValueError) as exc:
        logger.debug("physical core count unavailable: %s", exc)
        return None


def _total_ram_gb() -> float | None:
    try:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        function = kernel32.GlobalMemoryStatusEx
        function.argtypes = [ctypes.POINTER(_MemoryStatusEx)]
        function.restype = wintypes.BOOL
        status = _MemoryStatusEx()
        status.dwLength = ctypes.sizeof(_MemoryStatusEx)
        if not function(ctypes.byref(status)):
            return None
        return round(status.ullTotalPhys / (1024**3), 1)
    except (AttributeError, OSError) as exc:
        logger.debug("total RAM unavailable: %s", exc)
        return None


def _gpu_adapters() -> tuple[str, ...]:
    try:
        import winreg

        names: list[str] = []
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, _GPU_CLASS_KEY) as key:
            for index in range(winreg.QueryInfoKey(key)[0]):
                try:
                    subkey_name = winreg.EnumKey(key, index)
                    with winreg.OpenKey(key, subkey_name) as subkey:
                        value, _ = winreg.QueryValueEx(subkey, "DriverDesc")
                except OSError:
                    continue
                if isinstance(value, str) and value.strip():
                    names.append(value.strip())
        return tuple(dict.fromkeys(names))
    except (ImportError, OSError) as exc:
        logger.debug("GPU adapters unavailable: %s", exc)
        return ()


def probe_evidence() -> HardwareEvidence:
    """Read CPU, memory, and GPU adapters; every failure leaves a field unknown."""
    logical = os.cpu_count()
    if sys.platform != "win32":
        return HardwareEvidence(logical_cores=logical)
    return HardwareEvidence(
        cpu_name=_cpu_name(),
        physical_cores=_physical_cores(),
        logical_cores=logical,
        ram_gb=_total_ram_gb(),
        gpu_adapters=_gpu_adapters(),
    )
