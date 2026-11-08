"""Non-executable public:all@fairPrice snapshots with causal receipt availability."""
import json
import re
import sqlite3
from pathlib import Path

from ..domain.market_models import decimal
from ..domain.model import iso, parse_ts
from ..domain.strategy import digest

SYMBOL = re.compile(r"[A-Z0-9]{3,24}\Z")
MAX_SYMBOLS = 1000
MAX_DB_BYTES = 128 * 1024 * 1024


def parse_fair_price(payload, *, received_at):
    """Validate the documented public full-snapshot shape as an untrusted mark."""
    if (received_at.tzinfo is None or type(payload) is not dict
            or set(payload) != {"ts", "prices"}
            or type(payload["prices"]) is not dict
            or not 1 <= len(payload["prices"]) <= MAX_SYMBOLS):
        raise ValueError("invalid public fair-price snapshot")
    event_at = parse_ts(payload["ts"])
    if (event_at - received_at).total_seconds() > 5:
        raise ValueError("future fair-price event is not yet available")
    quotes = {}
    for symbol, value in payload["prices"].items():
        if type(symbol) is not str or SYMBOL.fullmatch(symbol) is None:
            raise ValueError("invalid fair-price market")
        parsed = decimal(value, "fair price", positive=True)
        if parsed >= 10**30:
            raise ValueError("unbounded fair price")
        quotes[symbol] = format(parsed, "f")
    return {"schema": "public-fairprice-observation/1",
            "channel": "public:all@fairPrice",
            "event_at": iso(event_at), "available_at": iso(received_at),
            "prices": dict(sorted(quotes.items())),
            "source_authenticated": False, "executable_quote": False,
            "funded_authority": False,
            "basis": "Public fair midpoint only; not a bid, ask, executable depth, or authenticated private fill"}


class FairPriceJournal:
    """Append-only research-only mark store; never an entry or venue price source."""

    def __init__(self, path):
        path = Path(path)
        if path.is_symlink() or (path.exists() and (not path.is_file() or path.stat().st_size > MAX_DB_BYTES)):
            raise ValueError("invalid fair-price journal path")
        self.conn = sqlite3.connect(path, timeout=5, isolation_level=None)
        try:
            version = self.conn.execute("PRAGMA user_version").fetchone()[0]
            tables = {row[0] for row in self.conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if version not in (0, 1) or (version == 0 and tables):
                raise ValueError("unsupported fair-price journal schema")
            self.conn.execute("PRAGMA journal_mode=WAL")
            self.conn.execute("PRAGMA synchronous=FULL")
            if version == 0:
                self.conn.executescript("""BEGIN IMMEDIATE;
                    CREATE TABLE observations(
                        id TEXT NOT NULL, symbol TEXT NOT NULL,
                        event_at TEXT NOT NULL, available_at TEXT NOT NULL,
                        price TEXT NOT NULL, PRIMARY KEY(id,symbol));
                    CREATE INDEX observations_available ON observations(symbol,available_at);
                    CREATE TRIGGER fairprice_immutable BEFORE UPDATE ON observations
                      BEGIN SELECT RAISE(ABORT,'immutable fair price'); END;
                    CREATE TRIGGER fairprice_retained BEFORE DELETE ON observations
                      BEGIN SELECT RAISE(ABORT,'retain fair price'); END;
                    PRAGMA user_version=1; COMMIT;""")
            if self.conn.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                raise ValueError("fair-price journal integrity failed")
        except BaseException:
            self.conn.close()
            raise

    def __enter__(self):
        """Open a scoped immutable public-price observation session."""
        return self

    def __exit__(self, *_):
        """Close the scoped SQLite connection."""
        self.conn.close()

    def record(self, payload, *, received_at):
        """Atomically retain a bounded public snapshot with actual arrival time."""
        row = parse_fair_price(payload, received_at=received_at)
        key = digest((row["event_at"], row["available_at"], row["prices"]))[:32]
        self.conn.execute("BEGIN IMMEDIATE")
        try:
            for symbol, price in row["prices"].items():
                self.conn.execute(
                    "INSERT OR IGNORE INTO observations VALUES(?,?,?,?,?)",
                    (key, symbol, row["event_at"], row["available_at"], price))
            self.conn.commit()
        except BaseException:
            self.conn.rollback()
            raise
        return {"observation_id": key, "symbols_recorded": len(row["prices"]),
                "available_at": row["available_at"], "source_authenticated": False,
                "funded_authority": False}

    def valuation(self, symbol, *, as_of, max_age_seconds=120):
        """Read only prior available fair mid, never substitute it for tradeable bid."""
        if (type(symbol) is not str or SYMBOL.fullmatch(symbol) is None
                or as_of.tzinfo is None
                or type(max_age_seconds) is not int or not 1 <= max_age_seconds <= 600):
            raise ValueError("invalid fair-price valuation request")
        result = {"symbol": symbol, "as_of_exclusive": iso(as_of),
                  "status": "UNAVAILABLE", "derived_rate": None, "observed_rate": None,
                  "observation_at": None, "available_at": None,
                  "source": "public:all@fairPrice", "source_authenticated": False,
                  "executable_quote": False, "funded_authority": False}
        row = self.conn.execute(
            "SELECT price,event_at,available_at FROM observations "
            "WHERE symbol=? AND available_at<? ORDER BY available_at DESC LIMIT 1",
            (symbol, iso(as_of))).fetchone()
        if row is None:
            return result
        age = (as_of - parse_ts(row[2])).total_seconds()
        fresh = 0 <= age <= max_age_seconds
        return {**result, "status": "FRESH_NON_EXECUTABLE" if fresh else "STALE",
                "derived_rate": row[0] if fresh else None,
                "observed_rate": row[0], "observation_at": row[1],
                "available_at": row[2], "age_seconds": age}


def fairprice_action(root, action, value, *, received_at):
    """Route research-only public snapshot recording and retrospective read."""
    if type(value) is not dict:
        raise ValueError("invalid fair-price research request")
    if action == "fairprice-observe":
        if set(value) != {"payload"}:
            raise ValueError("fairprice-observe requires payload")
    elif action == "fairprice-read":
        if set(value) != {"symbol", "as_of"}:
            raise ValueError("fairprice-read requires symbol and as_of")
    else:
        raise ValueError("unsupported fair-price action")
    with FairPriceJournal(Path(root) / "fair_price.sqlite3") as journal:
        if action == "fairprice-observe":
            return journal.record(value["payload"], received_at=received_at)
        at = parse_ts(value["as_of"])
        if at > received_at:
            raise ValueError("future fair-price valuation")
        return journal.valuation(value["symbol"], as_of=at)
