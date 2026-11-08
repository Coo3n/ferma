"""Железо фермы без сторонних пакетов. `exact[поле]` истинно только для измеренного."""
from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

GB = 1024 ** 3


def _ram_bytes() -> int | None:
    try:
        if sys.platform == "win32":
            import ctypes

            class MS(ctypes.Structure):
                _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                            ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                            ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                            ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                            ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
            st = MS()
            st.dwLength = ctypes.sizeof(MS)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(st)):
                return int(st.ullTotalPhys)
            return None
        if sys.platform == "darwin":
            out = subprocess.run(["sysctl", "-n", "hw.memsize"], capture_output=True, text=True, timeout=5)
            return int(out.stdout.strip())
        for line in Path("/proc/meminfo").read_text().splitlines():
            if line.startswith("MemTotal:"):
                return int(line.split()[1]) * 1024
    except Exception:
        return None
    return None


def _cpu_name() -> str | None:
    n = platform.processor()
    if n:
        return n
    try:
        for line in Path("/proc/cpuinfo").read_text().splitlines():
            if line.startswith("model name"):
                return line.split(":", 1)[1].strip()
    except Exception:
        pass
    return None


def _gpus() -> tuple[list, bool]:
    """(список, измерено ли)."""
    try:
        out = subprocess.run(["nvidia-smi", "--query-gpu=name,memory.total",
                              "--format=csv,noheader,nounits"],
                             capture_output=True, text=True, timeout=8)
        if out.returncode == 0 and out.stdout.strip():
            res = []
            for line in out.stdout.strip().splitlines():
                name, _, mem = line.rpartition(",")
                res.append({"name": name.strip(), "vram_gb": round(float(mem) / 1024, 1)})
            return res, True
    except Exception:
        pass
    try:
        out = subprocess.run(["rocm-smi", "--showproductname", "--showmeminfo", "vram", "--json"],
                             capture_output=True, text=True, timeout=8)
        if out.returncode == 0 and out.stdout.strip():
            import json
            res = []
            for card in json.loads(out.stdout).values():
                name = card.get("Card Series") or card.get("Card series") or "AMD GPU"
                tot = card.get("VRAM Total Memory (B)")
                res.append({"name": name, **({"vram_gb": round(int(tot) / GB, 1)} if tot else {})})
            if res:
                return res, True
    except Exception:
        pass
    if sys.platform == "darwin":
        try:
            out = subprocess.run(["system_profiler", "SPDisplaysDataType"],
                                 capture_output=True, text=True, timeout=10)
            names = [l.split(":", 1)[1].strip() for l in out.stdout.splitlines()
                     if l.strip().startswith("Chipset Model:")]
            return [{"name": n} for n in names], False
        except Exception:
            pass
    return [], False


def collect(disk_path: str | None = None) -> dict:
    ram = _ram_bytes()
    cpu = _cpu_name()
    try:
        disk = round(shutil.disk_usage(disk_path or str(Path.home())).free / GB, 1)
    except Exception:
        disk = None
    gpus, gpu_exact = _gpus()
    cores = os.cpu_count()
    return {
        "os": f"{platform.system()} {platform.release()}".strip(),
        "arch": platform.machine(),
        "cpu": {"name": cpu, "cores": cores},
        "ram_gb": round(ram / GB, 1) if ram else None,
        "disk_free_gb": disk,
        "gpus": gpus,
        "exact": {"os": True, "arch": True, "cpu": bool(cpu), "cores": bool(cores),
                  "ram_gb": ram is not None, "disk_free_gb": disk is not None,
                  "gpus": gpu_exact},
    }
