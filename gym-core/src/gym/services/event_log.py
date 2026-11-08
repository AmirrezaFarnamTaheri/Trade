"""Structured JSON event log: one object per line in <store>/events.jsonl, rotated by size."""
import json
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

log = logging.getLogger("gym")


class JsonLines(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        return json.dumps({"ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S") + f".{int(record.msecs):03d}",
                           "level": record.levelname.lower(), "event": record.getMessage(),
                           **getattr(record, "fields", {})}, ensure_ascii=False, default=str)


def configure(store: Path, max_bytes: int = 50 * 2**20, backups: int = 3) -> Path:
    """Attach the rotating JSON file once; without it, events go nowhere (tests and one-shot commands)."""
    path = store / "events.jsonl"
    if not any(isinstance(h, RotatingFileHandler) for h in log.handlers):
        handler = RotatingFileHandler(path, maxBytes=max_bytes, backupCount=backups, encoding="utf-8")
        handler.setFormatter(JsonLines())
        log.addHandler(handler)
        log.setLevel(logging.INFO)
    return path


def event(name: str, **fields) -> None:
    log.info(name, extra={"fields": fields})
