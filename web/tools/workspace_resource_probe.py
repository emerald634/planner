"""Isolated password memory probe; no settings, databases, credentials or network."""

import json
import os
import platform
import secrets
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path


def peak_bytes():
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes

        class Counters(ctypes.Structure):
            _fields_ = [("cb", wintypes.DWORD), ("faults", wintypes.DWORD)] + [
                (name, ctypes.c_size_t)
                for name in (
                    "peak",
                    "current",
                    "paged_peak",
                    "paged",
                    "nonpaged_peak",
                    "nonpaged",
                    "pagefile",
                    "pagefile_peak",
                )
            ]

        info = Counters()
        info.cb = ctypes.sizeof(info)
        get = ctypes.windll.kernel32.GetCurrentProcess
        get.restype = wintypes.HANDLE
        measure = ctypes.windll.psapi.GetProcessMemoryInfo
        measure.argtypes = [wintypes.HANDLE, ctypes.POINTER(Counters), wintypes.DWORD]
        measure.restype = wintypes.BOOL
        if not measure(get(), ctypes.byref(info), info.cb):
            raise ctypes.WinError()
        return info.peak
    import resource

    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024


def main():
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
    from app.core.security import hash_password, verify_password

    password = secrets.token_urlsafe(20)
    hashed = hash_password(password)
    start = time.perf_counter()
    with ThreadPoolExecutor(2) as pool:
        assert all(pool.map(lambda _: verify_password(password, hashed), range(2)))
    result = {
        "platform": platform.system(),
        "python": platform.python_version(),
        "simultaneous_hashes": 2,
        "argon2_parameters": hashed.split("$")[3],
        "peak_process_mib": round(peak_bytes() / 2**20, 2),
        "two_verifications_seconds": round(time.perf_counter() - start, 3),
        "linux_production_measured": False,
        "note": "Synthetic isolated process, not server headroom or PostgreSQL/browser memory.",
    }
    print(json.dumps(result))


if __name__ == "__main__":
    main()
