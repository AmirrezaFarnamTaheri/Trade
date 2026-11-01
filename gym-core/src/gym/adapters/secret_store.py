"""Per-user Windows DPAPI storage for Wallex API keys. Never prints or logs a key.

ponytail: current-user DPAPI, not the plan's service-owned T2 store; move to
service-context DPAPI behind the Executor T2 pipe when the service is installed.
"""
from __future__ import annotations

import ctypes
import os
import re
from ctypes import wintypes
from pathlib import Path

ROLES = ("read", "trade")
_KEY = re.compile(r"[0-9]{1,12}\|[A-Za-z0-9]{20,128}\Z")


class _Blob(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]


def _crypt(data: bytes, protect: bool) -> bytes:
    if os.name != "nt":
        raise OSError("DPAPI key storage requires Windows")
    crypt32, kernel32 = ctypes.windll.crypt32, ctypes.windll.kernel32
    buf = ctypes.create_string_buffer(data, len(data))
    src, out = _Blob(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char))), _Blob()
    fn = crypt32.CryptProtectData if protect else crypt32.CryptUnprotectData
    # CRYPTPROTECT_UI_FORBIDDEN = 1
    if not fn(ctypes.byref(src), None, None, None, None, 1, ctypes.byref(out)):
        raise OSError("DPAPI operation failed")
    try:
        return ctypes.string_at(out.pbData, out.cbData)
    finally:
        kernel32.LocalFree(out.pbData)


def default_dir() -> Path:
    return Path(os.environ.get("LOCALAPPDATA", Path.home())) / "TradingGYM" / "keys"


def _path(role: str, root: Path | None) -> Path:
    if role not in ROLES:
        raise ValueError("key role must be read or trade")
    return (root or default_dir()) / f"wallex-{role}.dpapi"


def save(role: str, key: str, root: Path | None = None) -> Path:
    key = key.strip()
    if not _KEY.fullmatch(key):
        raise ValueError("not a Wallex API key (expected <id>|<secret>)")
    path = _path(role, root)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_bytes(_crypt(key.encode(), True))
    os.replace(tmp, path)
    return path


def load(role: str, root: Path | None = None) -> str:
    path = _path(role, root)
    if not path.is_file():
        raise ValueError(f"no {role} key stored; run: gymctl key set {role}")
    return _crypt(path.read_bytes(), False).decode()


def masked(key: str) -> str:
    return key.split("|", 1)[0] + "|…" + key[-4:]
