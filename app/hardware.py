"""What this PC has: processor, memory, graphics cards.

Read once at start and again when the user asks. Nothing here loads a model
or touches the graphics card; it only asks Windows what is installed.
"""

from __future__ import annotations

import ctypes
import json
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

NO_WINDOW = 0x08000000 if os.name == "nt" else 0

_VIRTUAL = ("microsoft basic", "microsoft remote", "parsec", "virtual", "citrix", "idd ", "meta ", "oculus", "displaylink", "spacedesk")
_VIDEO_CLASS = r"SYSTEM\CurrentControlSet\Control\Class\{4d36e968-e325-11ce-bfc1-08002be10318}"


def _cpu_name() -> str:
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DESCRIPTION\System\CentralProcessor\0") as k:
            return " ".join(winreg.QueryValueEx(k, "ProcessorNameString")[0].split())
    except (ImportError, OSError):
        return platform.processor() or "Unknown processor"


def _cpu_feature(number: int) -> bool:
    """IsProcessorFeaturePresent: 40 is AVX2, 41 is AVX-512F."""
    try:
        return bool(ctypes.windll.kernel32.IsProcessorFeaturePresent(number))
    except (AttributeError, OSError):
        return False


def _ram_gb(free: bool = False) -> float:
    """The PC's memory in GB; with free=True, how much of it nothing is using right now."""
    try:

        class MemStatus(ctypes.Structure):
            _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong)] + [
                (n, ctypes.c_ulonglong)
                for n in ("ullTotalPhys", "ullAvailPhys", "ullTotalPageFile", "ullAvailPageFile", "ullTotalVirtual", "ullAvailVirtual", "ullAvailExtendedVirtual")
            ]

        ms = MemStatus()
        ms.dwLength = ctypes.sizeof(MemStatus)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(ms)):
            return round((ms.ullAvailPhys if free else ms.ullTotalPhys) / 1024**3, 1)
    except (AttributeError, OSError):
        pass
    return 0.0


def free_ram_gb() -> float:
    """Memory nothing is using right now, in GB. 0.0 when it cannot be read."""
    return _ram_gb(free=True)


def _present_adapters() -> list[dict]:
    """The graphics adapters that are plugged in right now, by name."""
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "Get-CimInstance Win32_VideoController | Select-Object Name,AdapterRAM,DriverVersion | ConvertTo-Json -Compress"],
            capture_output=True, text=True, timeout=30, creationflags=NO_WINDOW,
        ).stdout.strip()  # fmt: skip
        found = json.loads(out) if out else []
        return [found] if isinstance(found, dict) else found
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return []


def _registry_memory() -> dict[str, float]:
    """Dedicated graphics memory by adapter name. Windows' own listing stops
    counting at 4 GB, the driver's registry entry does not."""
    found: dict[str, float] = {}
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, _VIDEO_CLASS) as cls:
            for i in range(64):
                try:
                    sub = winreg.EnumKey(cls, i)
                except OSError:
                    break
                try:
                    with winreg.OpenKey(cls, sub) as k:
                        name = str(winreg.QueryValueEx(k, "DriverDesc")[0])
                        try:
                            size = winreg.QueryValueEx(k, "HardwareInformation.qwMemorySize")[0]
                        except OSError:
                            size = winreg.QueryValueEx(k, "HardwareInformation.MemorySize")[0]
                        if isinstance(size, bytes):
                            size = int.from_bytes(size[:8], "little")
                        found[name] = max(found.get(name, 0.0), round(int(size) / 1024**3, 1))
                except (OSError, ValueError, TypeError):
                    continue
    except (ImportError, OSError):
        pass
    return found


def _nvidia() -> list[dict]:
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,memory.total,driver_version", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=20, creationflags=NO_WINDOW,
        )  # fmt: skip
        cards = []
        for line in out.stdout.strip().splitlines():
            name, mem, driver = (x.strip() for x in line.split(","))
            cards.append({"name": name, "vram_gb": round(int(mem) / 1024, 1), "driver": driver})
        return cards
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return []


def vendor_of(name: str) -> str:
    n = name.lower()
    if any(w in n for w in ("nvidia", "geforce", "quadro", " rtx", " gtx")) or n.startswith(("rtx", "gtx")):
        return "nvidia"
    if any(w in n for w in ("radeon", "amd", "firepro")):
        return "amd"
    if any(w in n for w in ("intel", "iris", "arc(", "arc ")):
        return "intel"
    return "other"


def is_integrated(name: str) -> bool:
    """Graphics built into the processor: it shares the PC's RAM and is slow."""
    n = name.lower()
    if vendor_of(name) == "intel":
        return "arc" not in n or "arc graphics" in n  # "Arc A770" is a card, "Arc Graphics" sits in the CPU
    if vendor_of(name) == "amd":
        return "radeon(tm) graphics" in n or "vega" in n or ("radeon graphics" in n and " rx" not in n)
    return False


def detect() -> dict:
    gpus: list[dict] = []
    if os.name == "nt":
        memory = _registry_memory()
        smi = {c["name"].lower(): c for c in _nvidia()}
        for a in _present_adapters():
            name = str(a.get("Name") or "").strip()
            if not name or any(v in name.lower() for v in _VIRTUAL):
                continue
            vram = memory.get(name) or round(int(a.get("AdapterRAM") or 0) / 1024**3, 1)
            driver = str(a.get("DriverVersion") or "")
            match = next((c for key, c in smi.items() if key in name.lower() or name.lower() in key), None)
            if match:
                vram, driver = match["vram_gb"], match["driver"]
            gpus.append({"name": name, "vendor": vendor_of(name), "vram_gb": vram, "driver": driver, "integrated": is_integrated(name)})
        if not gpus:  # the adapter listing failed; nvidia-smi alone still knows the NVIDIA cards
            gpus = [{"name": c["name"], "vendor": "nvidia", "vram_gb": c["vram_gb"], "driver": c["driver"], "integrated": False} for c in smi.values()]
    gpus.sort(key=lambda g: (g["integrated"], -g["vram_gb"]))
    threads = os.cpu_count() or 1
    try:
        free = round(shutil.disk_usage(Path(__file__).resolve().parents[1]).free / 1024**3, 1)
    except OSError:
        free = 0.0
    return {
        "os": f"{platform.system()} {platform.release()}",
        "windows": os.name == "nt",
        "cpu": {"name": _cpu_name(), "threads": threads, "avx2": _cpu_feature(40), "avx512": _cpu_feature(41)},
        "ram_gb": _ram_gb(),
        "gpus": gpus,
        "disk_free_gb": free,
    }


if __name__ == "__main__":
    json.dump(detect(), sys.stdout, indent=2)
