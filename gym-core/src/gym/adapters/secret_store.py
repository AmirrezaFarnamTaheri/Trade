"""Per-user Windows DPAPI storage for Wallex API keys. Never prints or logs a key.

ponytail: current-user DPAPI, not the plan's service-owned T2 store; move to
service-context DPAPI behind the Executor T2 pipe when the service is installed.
"""
from __future__ import annotations

import ctypes
import os
import re
from ctypes import wintypes
from datetime import date, timedelta
from pathlib import Path

ROLES = ("read", "trade")
_KEY = re.compile(r"[0-9]{1,12}\|[A-Za-z0-9]{20,128}\Z")


class _Blob(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]


def _entropy(purpose: str) -> bytes:
    """Purpose-bound secondary entropy: a blob opens only for the purpose it was sealed for, and only via this code."""
    return f"TradingGYM/gym-core/{purpose}/v1".encode()


def _crypt(data: bytes, protect: bool, purpose: str | None = None) -> bytes:
    """DPAPI protect/unprotect; `purpose=None` is the legacy no-entropy form, used only to migrate old blobs."""
    if os.name != "nt":
        raise OSError("DPAPI key storage requires Windows")
    crypt32, kernel32 = ctypes.windll.crypt32, ctypes.windll.kernel32
    buf = ctypes.create_string_buffer(data, len(data))
    src, out = _Blob(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char))), _Blob()
    entropy = None
    if purpose is not None:
        salt = _entropy(purpose)
        salt_buf = ctypes.create_string_buffer(salt, len(salt))
        entropy = ctypes.byref(_Blob(len(salt), ctypes.cast(salt_buf, ctypes.POINTER(ctypes.c_char))))
    fn = crypt32.CryptProtectData if protect else crypt32.CryptUnprotectData
    # CRYPTPROTECT_UI_FORBIDDEN = 1
    if not fn(ctypes.byref(src), None, entropy, None, None, 1, ctypes.byref(out)):
        raise OSError("DPAPI operation failed")
    try:
        return ctypes.string_at(out.pbData, out.cbData)
    finally:
        kernel32.LocalFree(out.pbData)


_REPARSE_POINT = 0x400  # FILE_ATTRIBUTE_REPARSE_POINT: symlinks and junctions


def _refuse_links(path: Path) -> None:
    """A key file, its temp file or its folder must not be a symlink or junction that redirects the write."""
    for p in (path, path.parent):
        try:
            st = os.lstat(p)
        except FileNotFoundError:
            continue
        if p.is_symlink() or getattr(st, "st_file_attributes", 0) & _REPARSE_POINT:
            raise ValueError(f"refusing linked secret path: {p}")


_OWNER, _DACL, _PROTECTED_DACL = 0x1, 0x4, 0x80000000


def _current_sid() -> str:
    """String SID of this process's user (TokenUser)."""
    advapi32, kernel32 = ctypes.windll.advapi32, ctypes.windll.kernel32
    advapi32.OpenProcessToken.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE)]
    kernel32.GetCurrentProcess.restype = wintypes.HANDLE
    token = wintypes.HANDLE()
    if not advapi32.OpenProcessToken(kernel32.GetCurrentProcess(), 0x0008, ctypes.byref(token)):  # TOKEN_QUERY
        raise OSError("cannot open the process token")
    try:
        size = wintypes.DWORD()
        advapi32.GetTokenInformation(token, 1, None, 0, ctypes.byref(size))  # TokenUser
        buf = ctypes.create_string_buffer(size.value)
        if not advapi32.GetTokenInformation(token, 1, buf, size, ctypes.byref(size)):
            raise OSError("cannot read the token user")
        return _sid_text(ctypes.cast(buf, ctypes.POINTER(ctypes.c_void_p))[0])
    finally:
        kernel32.CloseHandle(token)


def _sid_text(sid) -> str:
    advapi32, kernel32 = ctypes.windll.advapi32, ctypes.windll.kernel32
    advapi32.ConvertSidToStringSidW.argtypes = [ctypes.c_void_p, ctypes.POINTER(wintypes.LPWSTR)]
    text = wintypes.LPWSTR()
    if not advapi32.ConvertSidToStringSidW(sid, ctypes.byref(text)):
        raise OSError("cannot format a SID")
    try:
        return text.value
    finally:
        kernel32.LocalFree(text)


def _protect(path: Path) -> None:
    """Protected DACL granting only this user full access: no inherited ACEs from the profile folder (S-12)."""
    if os.name != "nt":
        os.chmod(path, 0o600)
        return
    advapi32, kernel32 = ctypes.windll.advapi32, ctypes.windll.kernel32
    advapi32.ConvertStringSecurityDescriptorToSecurityDescriptorW.argtypes = [
        wintypes.LPCWSTR, wintypes.DWORD, ctypes.POINTER(ctypes.c_void_p), ctypes.c_void_p]
    advapi32.SetFileSecurityW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, ctypes.c_void_p]
    descriptor = ctypes.c_void_p()
    if not advapi32.ConvertStringSecurityDescriptorToSecurityDescriptorW(
            f"D:P(A;;FA;;;{_current_sid()})", 1, ctypes.byref(descriptor), None):
        raise OSError("cannot build the key file DACL")
    try:
        if not advapi32.SetFileSecurityW(str(path), _DACL | _PROTECTED_DACL, descriptor):
            raise OSError("cannot protect the key file")
    finally:
        kernel32.LocalFree(descriptor)


def _owner(path: Path) -> str:
    advapi32 = ctypes.windll.advapi32
    advapi32.GetFileSecurityW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD,
                                          ctypes.POINTER(wintypes.DWORD)]
    advapi32.GetSecurityDescriptorOwner.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p),
                                                    ctypes.POINTER(wintypes.BOOL)]
    size = wintypes.DWORD()
    advapi32.GetFileSecurityW(str(path), _OWNER, None, 0, ctypes.byref(size))
    buf = ctypes.create_string_buffer(size.value)
    if not advapi32.GetFileSecurityW(str(path), _OWNER, buf, size, ctypes.byref(size)):
        raise OSError("cannot read the key file owner")
    sid, defaulted = ctypes.c_void_p(), wintypes.BOOL()
    if not advapi32.GetSecurityDescriptorOwner(buf, ctypes.byref(sid), ctypes.byref(defaulted)) or not sid:
        raise OSError("key file has no owner")
    return _sid_text(sid)


def _check_owner(path: Path) -> None:
    """A key file planted by another account (or an administrator) is refused, not decrypted."""
    if os.name == "nt" and _owner(path) != _current_sid():
        raise ValueError(f"refusing a key file owned by another account: {path}")


def _seal(path: Path, secret: str, purpose: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    _refuse_links(path)
    _refuse_links(tmp)
    tmp.unlink(missing_ok=True)
    tmp.touch()
    _protect(tmp)  # the DACL is in place before any ciphertext is written, and moves with the rename
    tmp.write_bytes(_crypt(secret.encode(), True, purpose))
    os.replace(tmp, path)
    return path


def _unseal(path: Path, purpose: str) -> str:
    _refuse_links(path)
    _check_owner(path)
    blob = path.read_bytes()
    try:
        return _crypt(blob, False, purpose).decode()
    except OSError:
        legacy = _crypt(blob, False).decode()  # sealed before entropy was added; re-seal once
        _seal(path, legacy, purpose)
        return legacy


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
    return _seal(_path(role, root), key, f"wallex-{role}")


def load(role: str, root: Path | None = None) -> str:
    path = _path(role, root)
    if not path.is_file():
        raise ValueError(f"no {role} key stored; run: gymctl key set {role}")
    return _unseal(path, f"wallex-{role}")


def save_backup_passphrase(phrase: str, root: Path | None = None) -> Path:
    """Offline-backup passphrase for unattended backups, sealed to this Windows user (DPAPI)."""
    if len(phrase) < 12:
        raise ValueError("backup passphrase must be at least 12 characters")
    return _seal((root or default_dir()) / "backup-passphrase.dpapi", phrase, "backup-passphrase")


def load_backup_passphrase(root: Path | None = None) -> str:
    path = (root or default_dir()) / "backup-passphrase.dpapi"
    if not path.is_file():
        raise ValueError("no stored backup passphrase; run: gymctl key set-backup")
    return _unseal(path, "backup-passphrase")


MAX_KEY_DAYS = 90  # api-docs.wallex.ir: a key lives at most 90 days and cannot be renewed


def save_expiry(role: str, expires: date, today: date, root: Path | None = None) -> Path:
    """Record the key's chosen expiry (not secret) so `key show` can warn before reads start failing."""
    if not today <= expires <= today + timedelta(days=MAX_KEY_DAYS):
        raise ValueError(f"expiry must be between today and {MAX_KEY_DAYS} days from today")
    path = _path(role, root).with_suffix(".expires")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(expires.isoformat(), "ascii")
    return path


def clear_expiry(role: str, root: Path | None = None) -> None:
    _path(role, root).with_suffix(".expires").unlink(missing_ok=True)


def expiry_note(role: str, today: date, root: Path | None = None) -> str:
    path = _path(role, root).with_suffix(".expires")
    if not path.is_file():
        return f"expiry unknown (set it with: gymctl key set {role} --expires YYYY-MM-DD)"
    expires = date.fromisoformat(path.read_text("ascii").strip())
    left = (expires - today).days
    if left < 0:
        return f"EXPIRED on {expires}; create a new key on Wallex"
    return f"expires {expires} ({left} days)" + ("; create a replacement soon" if left <= 14 else "")


def masked(key: str) -> str:
    return key.split("|", 1)[0] + "|…" + key[-4:]
