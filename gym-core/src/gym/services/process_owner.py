"""Local process ownership is an OS lock; saved timestamps alone never prove liveness."""
import errno
import json
import os
import re
import threading
from datetime import timedelta
from pathlib import Path

from ..domain.model import iso, parse_ts
from .collector import now_utc


def _lock(stream, acquire):
    stream.seek(0)
    if os.name == "nt":
        import msvcrt
        msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK if acquire else msvcrt.LK_UNLCK, 1)
    else:
        import fcntl
        fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB if acquire else fcntl.LOCK_UN)


class ProcessOwner:
    def __init__(self, root, key, *, store):
        if store not in ("live", "demo") or type(key) is not str or not re.fullmatch(r"[a-zA-Z0-9-]{1,80}", key):
            raise ValueError("invalid local process owner")
        self.path = Path(root) / "processes" / f"{store}-{key}.lock"
        self.body = {"store": store, "owner": key, "pid": os.getpid(), "started_at": iso(now_utc())}
        self.stop, self.thread, self.stream = threading.Event(), None, None
        self.error = None

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.path.is_symlink():
            raise ValueError("process owner must be a regular local file")
        self.stream = self.path.open("a+b", buffering=0)
        if self.path.stat().st_size == 0:
            self.stream.write(b" ")
        try:
            _lock(self.stream, True)
        except OSError as error:
            self.stream.close()
            if error.errno not in (errno.EACCES, errno.EAGAIN):
                raise
            raise ValueError("another local process owns this workload") from None
        try:
            self.beat()
            self.thread = threading.Thread(target=self._heartbeat, daemon=True)
            self.thread.start()
        except BaseException:
            _lock(self.stream, False)
            self.stream.close()
            raise
        return self

    def beat(self):
        self.body["heartbeat_at"] = iso(now_utc())
        self.stream.seek(1)
        # The locked inode is never replaced; a concurrent partial read is UNKNOWN.
        self.stream.truncate(1)
        self.stream.write(json.dumps(self.body).encode())

    def _heartbeat(self):
        while not self.stop.wait(5):
            try:
                self.beat()
            except OSError as error:
                self.error = error
                return

    def __exit__(self, *_):
        self.stop.set()
        self.thread.join()
        _lock(self.stream, False)
        self.stream.close()
        if self.error is not None:
            raise self.error


def process_status(root, *, store):
    directory = Path(root) / "processes"
    rows = []
    for path in sorted(directory.glob(f"{store}-*.lock"))[:100]:
        row = {"owner": path.stem[len(store) + 1:], "state": "UNKNOWN"}
        try:
            if path.is_symlink() or not path.is_file() or path.stat().st_size > 4096:
                raise ValueError("invalid process owner file")
            with path.open("r+b", buffering=0) as stream:
                try:
                    _lock(stream, True)
                except OSError as error:
                    if error.errno not in (errno.EACCES, errno.EAGAIN):
                        raise
                    held = True
                else:
                    held = False
                    _lock(stream, False)
                stream.seek(1)
                body = json.loads(stream.read(4096))
            age = now_utc() - parse_ts(body["heartbeat_at"])
            if body["store"] != store or body["owner"] != row["owner"]:
                raise ValueError("owner scope mismatch")
            row.update(pid=body["pid"], heartbeat_at=body["heartbeat_at"],
                       state="STOPPED" if not held else "ALIVE" if timedelta(0) <= age <= timedelta(seconds=20) else "HEARTBEAT_STALE")
        except (OSError, ValueError, KeyError, TypeError):
            pass
        rows.append(row)
    return {"owners": rows, "scope": "Instrumented local workloads only; OS lock plus recent heartbeat proves a responsive owner, not completed work or fresh market data. Uninstrumented/frozen campaigns remain UNKNOWN.",
            "funded_authority": False}
