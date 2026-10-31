"""market.db (SQLite WAL) and append-only Zstd raw segments with a manifest (spec §4.5, §5.7)."""
from __future__ import annotations

import hashlib
import io
import json
import sqlite3
import time as _time
from datetime import datetime
from pathlib import Path

import zstandard as zstd

from ..domain.model import UTC, BookTop, TradeTick, iso

# Forward-only migrations; index = schema version - 1.
MIGRATIONS = [
    """
    create table instruments(instrument_id text primary key, venue text, symbol text, base text, quote text,
        kind text, names text);
    create table instrument_specs(instrument_id text, valid_from text, valid_to text, spec text, source text,
        primary key(instrument_id, valid_from));
    create table trades(instrument_id text, ts_event text, ts_avail text, price text, qty text, aggressor text,
        seg_ref text);
    create index trades_avail on trades(instrument_id, ts_avail);
    create table book_top(instrument_id text, ts_event text, ts_avail text, bid text, ask text, bid_qty text,
        ask_qty text, depth_ref text, flags text);
    create index book_top_avail on book_top(instrument_id, ts_avail);
    create table quality_events(ts text, instrument_id text, flag text, detail text);
    create table segments(seg_id text primary key, path text, seq_from integer, seq_to integer, sha256 text,
        bytes integer, closed_at text);
    create table regime_events(seq integer primary key autoincrement, ts text, op text, rule_id text,
        body text, actor text);
    """,
    """
    create table venue_candles(instrument_id text, resolution text, t text, o text, h text, l text, c text, v text,
        fetched_at text, primary key(instrument_id, resolution, t));
    """,
]


def s(x) -> str | None:
    return None if x is None else str(x)


class MarketDB:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.c = sqlite3.connect(path, isolation_level=None)
        self.c.execute("pragma journal_mode=WAL")
        self.c.execute("pragma synchronous=NORMAL")
        v = self.c.execute("pragma user_version").fetchone()[0]
        for i, sql in enumerate(MIGRATIONS[v:], v + 1):
            self.c.executescript(f"begin; {sql}; pragma user_version={i}; commit;")

    def upsert_instrument(self, inst, names: dict, spec: dict, source: str, now: datetime):
        iid = f"{inst.venue}:{inst.symbol}"
        self.c.execute("insert or replace into instruments values(?,?,?,?,?,?,?)",
                       (iid, inst.venue, inst.symbol, inst.base, inst.quote, inst.kind, json.dumps(names, ensure_ascii=False)))
        body = json.dumps(spec, sort_keys=True, default=str)
        last = self.c.execute("select spec from instrument_specs where instrument_id=? and valid_to is null", (iid,)).fetchone()
        if last and last[0] == body:
            return
        self.c.execute("update instrument_specs set valid_to=? where instrument_id=? and valid_to is null", (iso(now), iid))
        self.c.execute("insert into instrument_specs values(?,?,?,?,?)", (iid, iso(now), None, body, source))

    def add_trade(self, t: TradeTick, seg_ref: str):
        self.c.execute("insert into trades values(?,?,?,?,?,?,?)", (f"wallex:{t.symbol}", iso(t.ts_event), iso(t.ts_avail),
                       str(t.price), str(t.qty), t.aggressor, seg_ref))

    def add_book_top(self, b: BookTop, depth_ref: str | None):
        self.c.execute("insert into book_top values(?,?,?,?,?,?,?,?,?)", (f"wallex:{b.symbol}", iso(b.ts_avail), iso(b.ts_avail),
                       s(b.bid), s(b.ask), s(b.bid_qty), s(b.ask_qty), depth_ref, ",".join(sorted(b.flags))))

    def upsert_candles(self, symbol: str, resolution: str, candles: list[dict], fetched_at: datetime):
        """Venue candles are revised while forming: the latest fetch of a period replaces the earlier one."""
        self.c.executemany("insert or replace into venue_candles values(?,?,?,?,?,?,?,?,?)",
                           [(f"wallex:{symbol}", resolution, iso(k["t"]), str(k["o"]), str(k["h"]), str(k["l"]),
                             str(k["c"]), str(k["v"]), iso(fetched_at)) for k in candles])

    def add_quality(self, now: datetime, symbol: str | None, flag: str, detail: str = ""):
        self.c.execute("insert into quality_events values(?,?,?,?)", (iso(now), symbol and f"wallex:{symbol}", flag, detail[:500]))

    def quality(self, limit: int = 50):
        return self.c.execute("select * from quality_events order by rowid desc limit ?", (limit,)).fetchall()

    # --- regulation ledger: every change is an immutable event; current set is a fold ---
    def put_rule(self, body: dict, op: str, actor: str, now: datetime) -> int:
        cur = self.c.execute("insert into regime_events(ts, op, rule_id, body, actor) values(?,?,?,?,?)",
                             (iso(now), op, str(body.get("id")), json.dumps(body, ensure_ascii=False), actor))
        return cur.lastrowid

    def rule_events(self, rule_id: str | None = None):
        q = "select seq, ts, op, rule_id, body, actor from regime_events"
        rows = self.c.execute(q + (" where rule_id=?" if rule_id else "") + " order by seq", (rule_id,) if rule_id else ())
        return [dict(seq=r[0], ts=r[1], op=r[2], rule_id=r[3], body=json.loads(r[4]), actor=r[5]) for r in rows]

    def rules_as_of(self, at: datetime | None = None) -> tuple[int, dict[str, dict]]:
        """Point-in-time rule vintage: fold events recorded at or before `at`."""
        version, cur = 0, {}
        for e in self.rule_events():
            if at and e["ts"] > iso(at):
                break
            version, cur[e["rule_id"]] = e["seq"], e["body"]
        return version, cur

    def add_segment(self, seg_id, path, seq_from, seq_to, sha, nbytes, now):
        self.c.execute("insert or replace into segments values(?,?,?,?,?,?,?)", (seg_id, str(path), seq_from, seq_to, sha, nbytes, iso(now)))


class SegmentWriter:
    """Raw frames, append-only, one Zstd file per UTC hour; manifest row on rotate/close."""

    def __init__(self, root: Path, db: MarketDB, flush_s: float = 2.0):
        self.root, self.db, self.flush_s = root, db, flush_s
        self.seq, self.f, self.w, self.hour = 0, None, None, None
        self.last_flush = 0.0

    def _open(self, hour: str):
        self.close()
        d = self.root / hour[:8]
        d.mkdir(parents=True, exist_ok=True)
        n = 0
        while (p := d / f"{hour[8:]}-{n}.jsonl.zst").exists():
            n += 1
        self.path, self.hour, self.seq_from = p, hour, self.seq + 1
        self.f = open(p, "wb")
        self.w = zstd.ZstdCompressor(level=3).stream_writer(self.f, closefd=False)

    def write(self, src: str, raw: str, now: datetime) -> str:
        hour = now.astimezone(UTC).strftime("%Y%m%d%H")
        if hour != self.hour:
            self._open(hour)
        self.seq += 1
        line = {"seq": self.seq, "src": src, "t": iso(now), "sha256": hashlib.sha256(raw.encode()).hexdigest(), "raw": raw}
        self.w.write((json.dumps(line, ensure_ascii=False) + "\n").encode())
        if _time.monotonic() - self.last_flush > self.flush_s:
            self.w.flush(zstd.FLUSH_BLOCK)  # readable up to here after a crash
            self.last_flush = _time.monotonic()
        return f"{self.path.relative_to(self.root).as_posix()}#{self.seq}"

    def close(self):
        if not self.w:
            return
        self.w.flush(zstd.FLUSH_FRAME)
        self.w.close()
        self.f.close()
        data = self.path.read_bytes()
        self.db.add_segment(self.path.relative_to(self.root).as_posix(), self.path, self.seq_from, self.seq,
                            hashlib.sha256(data).hexdigest(), len(data), datetime.now(UTC))
        self.w = self.f = self.hour = None


def read_segment(path: Path) -> list[dict]:
    with open(path, "rb") as f:
        text = io.TextIOWrapper(zstd.ZstdDecompressor().stream_reader(f, read_across_frames=True), "utf-8")
        return [json.loads(line) for line in text if line.strip()]
