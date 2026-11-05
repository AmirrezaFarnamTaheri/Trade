"""Fixed installed entrypoint; never receives code, module names or executable paths from MCP."""
import json
import os
from pathlib import Path
import sys

from .research_mcp import serve_stdio


def boundary_probe(root):
    """Open-only negative probes from the actual R0 Python token; never send commands or write data."""
    import ctypes as c
    from ctypes import wintypes as w

    kernel = c.WinDLL("kernel32", use_last_error=True)
    advapi = c.WinDLL("advapi32", use_last_error=True)
    kernel.CreateFileW.argtypes = [w.LPCWSTR, w.DWORD, w.DWORD, c.c_void_p, w.DWORD, w.DWORD, w.HANDLE]
    kernel.CreateFileW.restype = w.HANDLE
    kernel.CloseHandle.argtypes = [w.HANDLE]
    advapi.OpenSCManagerW.argtypes = [w.LPCWSTR, w.LPCWSTR, w.DWORD]
    advapi.OpenSCManagerW.restype = w.HANDLE
    advapi.OpenServiceW.argtypes = [w.HANDLE, w.LPCWSTR, w.DWORD]
    advapi.OpenServiceW.restype = w.HANDLE
    advapi.CloseServiceHandle.argtypes = [w.HANDLE]
    targets = json.loads((root.parent / "boundary.json").read_text(encoding="utf-8-sig"))
    if set(targets) != {"stop_pipe", "operate_pipe", "t2_pipe", "vault", "core_journal", "profile_canary", "service"}:
        raise ValueError("incomplete protected probe targets")
    results = {}
    for name in ("stop_pipe", "operate_pipe", "t2_pipe", "vault", "core_journal", "profile_canary"):
        # Minimal data rights catch partial grants; overlapped opens do not require SYNCHRONIZE.
        attempts = []
        for access in (0x1, 0x2, 0x4, 0xC0000000):
            handle = kernel.CreateFileW(targets[name], access, 7, None, 3, 0x40000000, None)
            if handle != c.c_void_p(-1).value:
                kernel.CloseHandle(handle)
                attempts.append("FAIL_OPENED")
            else:
                error = c.get_last_error()
                attempts.append("DENIED" if error == 5 else f"NOT_VERIFIED_WIN32_{error}")
        results[name] = ("FAIL_OPENED" if "FAIL_OPENED" in attempts else
                         next((value for value in attempts if value != "DENIED"), "DENIED"))
    manager = advapi.OpenSCManagerW(None, None, 1)
    if manager:
        service = advapi.OpenServiceW(manager, targets["service"], 2)  # SERVICE_CHANGE_CONFIG; do not modify.
        if service:
            advapi.CloseServiceHandle(service)
            results["service"] = "FAIL_OPENED"
        else:
            error = c.get_last_error()
            results["service"] = "DENIED" if error == 5 else f"NOT_VERIFIED_WIN32_{error}"
        advapi.CloseServiceHandle(manager)
    else:
        results["service"] = f"NOT_VERIFIED_SCM_{c.get_last_error()}"
    print(json.dumps({"probe": "actual_R0_child", "pid": os.getpid(), "results": results}), flush=True)
    return 0 if all(value == "DENIED" for value in results.values()) else 3


def main():
    if len(sys.argv) not in (2, 3) or (len(sys.argv) == 3 and sys.argv[2] != "--boundary-probe"):
        raise SystemExit("fixed R0 entrypoint expects published input directory [--boundary-probe]")
    root = Path(sys.argv[1])
    if not root.is_absolute():
        raise SystemExit("absolute published input directory required")
    probe_code = boundary_probe(root) if len(sys.argv) == 3 else 0
    server_code = serve_stdio(root)
    return probe_code or server_code


if __name__ == "__main__":
    raise SystemExit(main())
