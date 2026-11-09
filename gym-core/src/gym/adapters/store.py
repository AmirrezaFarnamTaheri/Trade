"""market.db (SQLite WAL) and append-only Zstd raw segments with a manifest (spec §4.5, §5.7)."""
from __future__ import annotations

import hashlib
import io
import json
import shutil
import sqlite3
import time as _time
from datetime import datetime, timedelta
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
    """
    create table candle_vintages(instrument_id text, resolution text, t text, o text, h text, l text, c text, v text,
        fetched_at text, primary key(instrument_id, resolution, t, fetched_at));
    insert into candle_vintages select * from venue_candles;
    create trigger retain_candle_vintage before delete on candle_vintages begin select raise(abort,'retain candle vintage'); end;
    create trigger freeze_candle_vintage before update on candle_vintages begin select raise(abort,'immutable candle vintage'); end;
    """,
    """
    create table collector_publication(singleton integer primary key check(singleton=1), through text not null);
    """,
    """
    alter table book_top add column depth text;
    """,
]


# The raw archive grows ~200 MB/hour with all markets; stop cleanly well before the volume fills.
MIN_FREE_BYTES = 5 * 1024**3


class DiskLow(RuntimeError):
    """The archive volume is nearly full. Collection stops; it is never retried."""


def s(x) -> str | None:
    return None if x is None else str(x)


class MarketDB:
    def __init__(self, path: Path, *, readonly=False):
        if readonly:
            self.c = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, isolation_level=None)
            return
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

    def add_book_top(self, b: BookTop, depth_ref: str | None, depth: str | None = None):
        self.c.execute("insert into book_top values(?,?,?,?,?,?,?,?,?,?)", (f"wallex:{b.symbol}", iso(b.ts_avail), iso(b.ts_avail),
                       s(b.bid), s(b.ask), s(b.bid_qty), s(b.ask_qty), depth_ref, ",".join(sorted(b.flags)), depth))

    def upsert_candles(self, symbol: str, resolution: str, candles: list[dict], fetched_at: datetime):
        """Retain each fetch; latest projection may advance but cannot erase older knowledge."""
        self.c.execute("SAVEPOINT candle_batch")
        try:
            for k in candles:
                row = (f"wallex:{symbol}", resolution, iso(k["t"]), *(str(k[name]) for name in "ohlcv"), iso(fetched_at))
                prior = self.c.execute("SELECT o,h,l,c,v FROM candle_vintages WHERE instrument_id=? AND resolution=? AND t=? AND fetched_at=?",
                                      (*row[:3], row[-1])).fetchone()
                if prior is not None and prior != row[3:8]:
                    raise ValueError("conflicting candle values at the same fetch identity")
                self.c.execute("INSERT OR IGNORE INTO candle_vintages VALUES(?,?,?,?,?,?,?,?,?)", row)
                self.c.execute("""INSERT INTO venue_candles VALUES(?,?,?,?,?,?,?,?,?)
                    ON CONFLICT(instrument_id,resolution,t) DO UPDATE SET o=excluded.o,h=excluded.h,l=excluded.l,
                    c=excluded.c,v=excluded.v,fetched_at=excluded.fetched_at WHERE excluded.fetched_at>venue_candles.fetched_at""", row)
            self.c.execute("RELEASE candle_batch")
        except BaseException:
            self.c.execute("ROLLBACK TO candle_batch")
            self.c.execute("RELEASE candle_batch")
            raise

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
        return [{"seq": r[0], "ts": r[1], "op": r[2], "rule_id": r[3], "body": json.loads(r[4]), "actor": r[5]} for r in rows]

    def rules_as_of(self, at: datetime | None = None) -> tuple[int, dict[str, dict]]:
        """Point-in-time rule vintage: fold events recorded at or before `at`."""
        version, cur = 0, {}
        for e in self.rule_events():
            if at and e["ts"] > iso(at):
                break
            version, cur[e["rule_id"]] = e["seq"], e["body"]
        return version, cur

    def rules_version_as_of(self, at: datetime | None = None) -> int:
        """The last seq rules_as_of(at) folds. Events are append-only, so it identifies that vintage exactly."""
        if at is None:
            return self.c.execute("select coalesce(max(seq), 0) from regime_events").fetchone()[0]
        return self.c.execute(
            "select coalesce(max(seq), 0) from regime_events where seq < "
            "coalesce((select min(seq) from regime_events where ts > ?), 9223372036854775807)", (iso(at),)).fetchone()[0]

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
        free = shutil.disk_usage(d).free
        if free < MIN_FREE_BYTES:
            raise DiskLow(f"only {free // 2**20} MiB free for {self.root}; move old day folders with "
                          "`gymctl raw-move` (or free space) before collecting again")
        n = 0
        while True:
            p = d / f"{hour[8:]}-{n}.jsonl.zst"
            try:
                self.f = open(p, "xb")  # noqa: SIM115 - the writer owns the file until close(); exclusive: a concurrent writer can never truncate this file
                break
            except FileExistsError:
                n += 1
        self.path, self.hour, self.seq_from = p, hour, self.seq + 1
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
        with open(self.path, "rb") as f:
            sha = hashlib.file_digest(f, "sha256").hexdigest()  # streamed; hourly files reach ~220 MB
        self.db.add_segment(self.path.relative_to(self.root).as_posix(), self.path, self.seq_from, self.seq,
                            sha, self.path.stat().st_size, datetime.now(UTC))
        self.w = self.f = self.hour = None


def move_raw_days(raw: Path, target: Path, before: str) -> list[str]:
    """Move whole raw/YYYYMMDD day folders strictly before `before` (never today's) to `target`.

    Refuses everything if any destination day exists, so a move never merges or overwrites.
    """
    import re
    if not re.fullmatch(r"[0-9]{8}", before):
        raise ValueError("before must be YYYYMMDD")
    cutoff = min(before, datetime.now(UTC).strftime("%Y%m%d"))  # the current UTC day may still be written
    days = sorted(d for d in raw.iterdir() if d.is_dir() and re.fullmatch(r"[0-9]{8}", d.name) and d.name < cutoff) if raw.is_dir() else []
    clashes = [d.name for d in days if (target / d.name).exists()]
    if clashes:
        raise ValueError(f"destination already has {', '.join(clashes)}; nothing moved")
    target.mkdir(parents=True, exist_ok=True)
    for day in days:
        shutil.move(day, target / day.name)
    return [d.name for d in days]


COMPACT_BUCKETS = {"1s": 19, "1min": 16}  # ISO prefix length that identifies the bucket


def compact_quotes(db: MarketDB, before: datetime, bucket: str, now: datetime) -> int:
    """Keep only the last quote row per market and bucket before `before`; returns rows removed.

    Replays over compacted time see one quote per bucket. The raw archive still holds every frame,
    and a COMPACTED quality event records the change so later runs can warn.
    """
    if bucket not in COMPACT_BUCKETS or before > now:
        raise ValueError("bucket must be 1s or 1min, and the cut must not be in the future")
    width, cut = COMPACT_BUCKETS[bucket], iso(before)
    db.c.execute("BEGIN IMMEDIATE")
    try:
        removed = db.c.execute(f"""DELETE FROM book_top WHERE ts_avail < ? AND rowid NOT IN (
            SELECT max(rowid) FROM book_top WHERE ts_avail < ? GROUP BY instrument_id, substr(ts_avail, 1, {width}))""",
                               (cut, cut)).rowcount
        db.add_quality(now, None, "COMPACTED", f"before={cut};bucket={bucket};rows={removed}")
        db.c.execute("COMMIT")
    except BaseException:
        db.c.execute("ROLLBACK")
        raise
    return removed


def verify_segments(db: MarketDB, roots: list[Path], since: str = "") -> dict:
    """Re-hash closed raw segments against the manifest; `roots` are the raw folder and any archive folders."""
    report = {"checked": 0, "missing": [], "mismatched": []}
    for seg_id, sha, size in db.c.execute("SELECT seg_id, sha256, bytes FROM segments WHERE seg_id >= ? ORDER BY seg_id", (since,)).fetchall():
        path = next((root / seg_id for root in roots if (root / seg_id).is_file()), None)
        if path is None:
            report["missing"].append(seg_id)
            continue
        with open(path, "rb") as f:
            digest = hashlib.file_digest(f, "sha256").hexdigest()
        report["checked"] += 1
        if digest != sha or path.stat().st_size != size:
            report["mismatched"].append(seg_id)
    return report


def storage_forecast(db: MarketDB, raw: Path, now: datetime) -> dict:
    """Free space on the archive volume and how long until collection stops at the floor, from the last day's growth."""
    since = iso(now - timedelta(hours=24))
    written = db.c.execute("SELECT coalesce(sum(bytes), 0), min(closed_at) FROM segments WHERE closed_at >= ?", (since,)).fetchone()
    hours = max(1.0, (now - datetime.fromisoformat(written[1])).total_seconds() / 3600) if written[1] else None
    per_hour = written[0] / hours if hours else None
    probe = raw if raw.exists() else raw.parent
    free = shutil.disk_usage(probe).free
    return {"free_bytes": free, "floor_bytes": MIN_FREE_BYTES, "growth_bytes_per_hour": round(per_hour) if per_hour else None,
            "hours_to_floor": round(max(0, free - MIN_FREE_BYTES) / per_hour, 1) if per_hour else None}


def read_segment(path: Path) -> list[dict]:
    with open(path, "rb") as f:
        text = io.TextIOWrapper(zstd.ZstdDecompressor().stream_reader(f, read_across_frames=True), "utf-8")
        return [json.loads(line) for line in text if line.strip()]
