"""Publish complete local receipts without truncating the previous copy."""
import os
from pathlib import Path
from tempfile import NamedTemporaryFile


def write_text(path: Path, text: str) -> None:
    staged = None
    try:
        with NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False) as output:
            staged = Path(output.name)
            output.write(text)
            output.flush()
            os.fsync(output.fileno())
        os.replace(staged, path)
    finally:
        if staged is not None:
            staged.unlink(missing_ok=True)
