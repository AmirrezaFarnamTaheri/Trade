"""Common command implementations; invocation stays in gym.cli."""
from __future__ import annotations

import os
from pathlib import Path

from ..adapters.store import MarketDB
from ..domain.model import strict_loads
from ..services.collector import now_utc
from ..services.rules import RuleService

DEFAULT_WATCH = "USDTTMN,BTCTMN,BTCUSDT,ETHTMN,ETHUSDT"
DEFAULT_PRESET = "usdt-irt-october-2026"
# Fee default: --fee per run, or set GYM_FEE_RATE once (e.g. `setx GYM_FEE_RATE 0.0015`).
DEFAULT_FEE = os.environ.get("GYM_FEE_RATE", "0.001")
FEE_HELP = f"fee rate per side (default {DEFAULT_FEE}; observed account fee 0.1%%, override with GYM_FEE_RATE)"


def default_data_root() -> Path:
    """Keep editable source checkouts on the repository-level data directory."""
    core = Path(__file__).resolve().parents[3]
    if core.name == "gym-core" and (core / "pyproject.toml").is_file():
        return core.parent / "data"
    # A separately installed wheel has no reliable checkout root.
    # Its caller must pass --data explicitly to choose a shared store.
    return Path("data")


def store_root(args) -> Path:
    # Demo data lives in its own directory and never mixes with real observations.
    return Path(args.data) / ("demo" if getattr(args, "demo", False) else "live")


def open_db(args, preset_at=None) -> MarketDB:
    db = MarketDB(store_root(args) / "market.db")
    if not db.rule_events():
        RuleService(db).preset(DEFAULT_PRESET, preset_at or now_utc(), actor="first-run")
    return db


def _strict_offline_json(path: str, *, max_bytes: int) -> dict:
    """Never deserialize raw authenticated venue responses or secret fields."""
    source = Path(path)
    if source.is_symlink() or not source.is_file() or not 1 <= source.stat().st_size <= max_bytes:
        raise ValueError("offline input must be a bounded unsymlinked regular JSON file")
    result = strict_loads(source.read_text("utf-8"), "offline JSON input")
    if type(result) is not dict:
        raise ValueError("offline input must be a JSON object")
    return result


def timedelta_ms(ms: int):
    from datetime import timedelta

    return timedelta(milliseconds=ms)
