"""Cross-process exclusive file locking and durable JSONL append for forward paper journals."""
from __future__ import annotations

import os
import time
from contextlib import contextmanager
from pathlib import Path

if os.name == "nt":
    import msvcrt
else:
    import fcntl


def _acquire(fd: int, timeout: float) -> None:
    deadline = time.monotonic() + timeout
    while True:
        try:
            if os.name == "nt":
                os.lseek(fd, 0, os.SEEK_SET)
                msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
            else:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return
        except OSError:
            if time.monotonic() >= deadline:
                raise TimeoutError("timed out waiting for forward journal lock") from None
            time.sleep(0.01)


def _release(fd: int) -> None:
    if os.name == "nt":
        os.lseek(fd, 0, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
    else:
        fcntl.flock(fd, fcntl.LOCK_UN)


@contextmanager
def journal_lock(journal_path: Path, *, timeout: float = 15.0):
    """Serialize read-decide-append on a forward journal across threads and processes."""
    journal_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = journal_path.with_suffix(journal_path.suffix + ".lock")
    fd = os.open(lock_path, os.O_CREAT | os.O_RDWR)
    try:
        if os.name == "nt" and os.fstat(fd).st_size == 0:
            os.write(fd, b"0")
        _acquire(fd, timeout)
        try:
            yield
        finally:
            _release(fd)
    finally:
        os.close(fd)


def append_jsonl(path: Path, line: str) -> None:
    """Durably append one complete JSONL record."""
    with path.open("a", encoding="utf-8") as handle:
        handle.write(line + "\n")
        handle.flush()
        os.fsync(handle.fileno())
