"""Bounded current-user DPAPI byte bridge for the trusted model gateway."""
from __future__ import annotations

import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from gym.adapters.secret_store import _crypt


def main(argv=None) -> int:
    args = sys.argv[1:] if argv is None else argv
    try:
        if len(args) != 1 or args[0] not in ("encrypt", "decrypt"):
            raise ValueError("operation")
        data = sys.stdin.buffer.read(65537)
        if not data or len(data) > 65536:
            raise ValueError("size")
        result = _crypt(data, args[0] == "encrypt")
        if not result or len(result) > 65536:
            raise ValueError("size")
        sys.stdout.buffer.write(result)
        sys.stdout.buffer.flush()
        return 0
    except Exception:  # noqa: BLE001 - last-resort handler; credential errors must never reach the parent
        print("error: model credential operation failed", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
