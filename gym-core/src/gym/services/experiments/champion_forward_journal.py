"""Prospective live forward paper journal for the v1 Champion Ensemble (Slow Core + 2h GRU-Ignition).

Strictly read-only against market.db / multi_venue_quotes.sqlite3; zero order authority (DISARMED).
Never touches v1 mix-journal.jsonl.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from statistics import median

import numpy as np

from ...adapters.candle_reader import load_keyed_candles, open_readonly_market_db
from ...domain.model import dec, parse_ts
from ...domain.multi_asset_research import BASE_13_SYMBOLS
from ...domain.strategy_sleeves import compute_slow_sleeves
from ...domain.timeframe_panel import BarPoint, resample_hourly_to_bucket
from .admm_helpers import (
    build_dated_returns_index,
    build_shrunk_horizon_cov,
    extract_daily_breadth,
    solve_s1_s5_admm_weights,
)
from .gru_engine import EnsembleGRU
from .gru_prototypes_study import _extract_2h_breakout_sequences
from .ignition_expansion_study import IGNITION_18_CRYPTO
from .leader_forward_journal import _package_engine_digest


def _resample_1min_to_1h(bars_1m: list[BarPoint], *, as_of: datetime | None = None) -> list[BarPoint]:
    """Aggregate 1-minute bars into complete closed 1-hour bars so live 2h bars stay fresh without unfinished bars."""
    buckets: dict[datetime, list[BarPoint]] = {}
    for b in bars_1m:
        h_start = b.ts_start.replace(minute=0, second=0, microsecond=0)
        buckets.setdefault(h_start, []).append(b)
    out: list[BarPoint] = []
    for h_start in sorted(buckets):
        h_avail = h_start + timedelta(hours=1)
        if as_of is not None and h_avail > as_of:
            continue
        grp = sorted(buckets[h_start], key=lambda x: x.ts_start)
        if len(grp) < 55:
            continue
        vol = sum(x.volume for x in grp)
        out.append(
            BarPoint(
                symbol=grp[0].symbol,
                ts_start=h_start,
                ts_avail=h_avail,
                open=grp[0].open,
                high=max(x.high for x in grp),
                low=min(x.low for x in grp),
                close=grp[-1].close,
                volume=vol,
                bar_source="stitched_1min",
                clock_complete=True,
                nonzero_volume_fraction=sum(1 for x in grp if x.volume > 0) / len(grp),
                last_trade_age_bars=0,
                entry_eligible=(vol > 0.0),
                mark_status="LIVE" if vol > 0.0 else "STALE_MARK",
            )
        )
    return out


def load_stitched_1h_panel(
    con,
    symbols: tuple[str, ...],
    *,
    limit_1h: int = 800,
    as_of: datetime | None = None,
) -> dict[str, list[BarPoint]]:
    """Load recent closed 1h candles stitched with only the missing tail of 1min bars resampled to 1h."""
    panel_1h: dict[str, list[BarPoint]] = {}
    for sym in symbols:
        bars_1h = load_keyed_candles(con, sym, "1h", limit=limit_1h, as_of=as_of)
        last_1h = bars_1h[-1].ts_start if bars_1h else None
        since_1m = (last_1h + timedelta(hours=1)).isoformat() if last_1h is not None else None
        bars_1m = load_keyed_candles(con, sym, "1min", limit=4000, as_of=as_of, since_iso=since_1m)
        extra_1h = [
            b for b in _resample_1min_to_1h(bars_1m, as_of=as_of)
            if last_1h is None or b.ts_start > last_1h
        ]
        panel_1h[sym] = bars_1h + extra_1h
    return panel_1h


def load_stitched_2h_panel(
    con,
    symbols: tuple[str, ...],
    *,
    limit_1h: int = 800,
    as_of: datetime | None = None,
) -> dict[str, list[BarPoint]]:
    """Load recent closed 1h candles stitched with fresh 1min tail, then resample into closed 2h bars."""
    panel_1h = load_stitched_1h_panel(con, symbols, limit_1h=limit_1h, as_of=as_of)
    panel_2h: dict[str, list[BarPoint]] = {}
    for sym, merged_1h in panel_1h.items():
        bars_2h = resample_hourly_to_bucket(merged_1h, 2, offset_hours=0) if merged_1h else []
        if as_of is not None:
            bars_2h = [b for b in bars_2h if b.ts_avail <= as_of and b.clock_complete]
        panel_2h[sym] = bars_2h
    return panel_2h


def train_and_freeze_gru_ignition(
    db_path: Path,
    model_path: Path,
    *,
    as_of: datetime | None = None,
    gold_symbol: str = "XAUTUSDT",
) -> dict:
    """Train 3-seed EnsembleGRU on strictly pre-registration 2h breakouts and save frozen JSON weights."""
    cutoff = as_of or datetime.now(UTC)
    purge_cutoff = cutoff - timedelta(hours=48)
    slow_syms = tuple(gold_symbol if s == "XAUTUSDT" else s for s in BASE_13_SYMBOLS)

    con = open_readonly_market_db(db_path)
    try:
        panel_1d = {s: load_keyed_candles(con, s, "1d", limit=2500) for s in slow_syms}
        panel_1h = {s: load_keyed_candles(con, s, "1h", limit=26000) for s in IGNITION_18_CRYPTO}
    finally:
        con.close()

    sigs_1d = compute_slow_sleeves(panel_1d, slow_syms, gold_symbol=gold_symbol)
    daily_breadth: dict[str, float] = {}
    for ts, d in sigs_1d.items():
        first = next(iter(d.values()), None)
        if first and first.crypto_breadth is not None:
            daily_breadth[ts.date().isoformat()] = first.crypto_breadth

    panel_2h = {s: resample_hourly_to_bucket(panel_1h[s], 2, offset_hours=0) for s in IGNITION_18_CRYPTO}
    dts, _, xs, ys = _extract_2h_breakout_sequences(panel_2h, IGNITION_18_CRYPTO, daily_breadth)
    keep = [k for k, dt in enumerate(dts) if dt < purge_cutoff]
    if len(keep) < 80:
        raise RuntimeError(f"Insufficient pre-cutoff breakout episodes ({len(keep)}) to train frozen GRU-Ignition")

    x_tr, y_tr = xs[keep], ys[keep]
    base_rate = float(np.mean(y_tr))
    model = EnsembleGRU(input_dim=6, hidden_dim=12, task="binary", seeds=(42, 101, 202))
    model.fit(x_tr, y_tr, epochs=24, batch_size=64, lr=4e-3, l2_reg=5e-3)

    meta = {
        "model_id": "GRU_IGNITION_18_2H_V1",
        "trained_at": cutoff.isoformat(),
        "purge_cutoff_utc": purge_cutoff.isoformat(),
        "episodes": len(keep),
        "base_win_rate": round(base_rate, 4),
        "seq_len": 36,
        "symbols": list(IGNITION_18_CRYPTO),
        "feature_names": ["z_ret", "hl_range", "log_vol_ratio", "rel_btc_ret", "daily_breadth", "candle_dir"],
    }
    model.save_json(model_path, metadata=meta)
    raw = model_path.read_bytes()
    return {
        "model_path": str(model_path),
        "bytes": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "metadata": meta,
    }


def _latest_live_quotes(
    wallex_con,
    mv_db: Path | None,
    symbols: tuple[str, ...],
    *,
    as_of: datetime | None = None,
) -> dict[str, dict]:
    """Fetch latest live L1 spread & mid from Wallex and Nobitex strictly <= as_of when supplied."""
    quotes: dict[str, dict] = {s: {} for s in symbols}
    as_of_iso = as_of.isoformat().replace("+00:00", "Z") if as_of is not None else None
    for sym in symbols:
        inst = wallex_con.execute("SELECT instrument_id FROM instruments WHERE symbol = ?", (sym,)).fetchone()
        if inst is None:
            continue
        if as_of_iso is not None:
            row = wallex_con.execute(
                "SELECT bid, ask, ts_avail FROM book_top "
                "WHERE instrument_id = ? AND ts_avail <= ? AND bid IS NOT NULL AND ask IS NOT NULL "
                "ORDER BY ts_avail DESC LIMIT 1",
                (inst[0], as_of_iso),
            ).fetchone()
        else:
            row = wallex_con.execute(
                "SELECT bid, ask, ts_avail FROM book_top "
                "WHERE instrument_id = ? AND bid IS NOT NULL AND ask IS NOT NULL "
                "ORDER BY ts_avail DESC LIMIT 1",
                (inst[0],),
            ).fetchone()
        if row:
            wb, wa = float(dec(row[0])), float(dec(row[1]))
            mid = 0.5 * (wb + wa)
            quotes[sym]["wallex_mid"] = round(mid, 6)
            quotes[sym]["wallex_spread_bps"] = round((wa - wb) / mid * 10000.0, 2) if mid > 0 else 0.0
            quotes[sym]["wallex_ts"] = row[2]

    if mv_db is not None and mv_db.is_file():
        mcon = open_readonly_market_db(mv_db)
        try:
            for sym in symbols:
                if as_of_iso is not None:
                    row = mcon.execute(
                        "SELECT bid, ask, spread_bps, ts_avail FROM venue_quotes "
                        "WHERE venue = 'nobitex' AND symbol = ? AND ts_avail <= ? ORDER BY ts_avail DESC LIMIT 1",
                        (sym, as_of_iso),
                    ).fetchone()
                else:
                    row = mcon.execute(
                        "SELECT bid, ask, spread_bps, ts_avail FROM venue_quotes "
                        "WHERE venue = 'nobitex' AND symbol = ? ORDER BY id DESC LIMIT 1",
                        (sym,),
                    ).fetchone()
                if row:
                    nb, na = float(dec(row[0])), float(dec(row[1]))
                    mid = 0.5 * (nb + na)
                    quotes[sym]["nobitex_mid"] = round(mid, 6)
                    quotes[sym]["nobitex_spread_bps"] = round(float(dec(row[2])), 2)
                    quotes[sym]["nobitex_ts"] = row[3]
        finally:
            mcon.close()

    for q in quotes.values():
        w_sp = q.get("wallex_spread_bps")
        n_sp = q.get("nobitex_spread_bps")
        if n_sp is not None and (w_sp is None or (0.5 * n_sp + 9.1) <= (0.5 * w_sp + 13.0)):
            q["recommended_venue"] = "nobitex"
        elif w_sp is not None:
            q["recommended_venue"] = "wallex"
        else:
            q["recommended_venue"] = "unknown"
    return quotes


def _score_live_2h_ignition(
    panel_2h: dict[str, list[BarPoint]],
    daily_breadth: dict[str, float],
    model: EnsembleGRU,
    base_prob: float,
) -> tuple[datetime | None, list[dict], dict[str, float]]:
    """Evaluate latest closed 2h bar across IGNITION_18_CRYPTO and score triggers with frozen GRU-Ignition."""
    btc_bars = panel_2h.get("BTCUSDT", [])
    btc_ret = {
        btc_bars[i].ts_avail: (btc_bars[i].close - btc_bars[i - 1].close) / btc_bars[i - 1].close
        for i in range(1, len(btc_bars))
        if btc_bars[i - 1].close > 0
    }
    latest_ts: datetime | None = None
    triggers: list[dict] = []

    for sym in IGNITION_18_CRYPTO:
        bars = panel_2h.get(sym, [])
        if len(bars) < 80:
            continue
        i = len(bars) - 1
        b = bars[i]
        if latest_ts is None or b.ts_avail > latest_ts:
            latest_ts = b.ts_avail
        day_br = daily_breadth.get(b.ts_avail.date().isoformat(), 0.0)
        if day_br < 0.45:
            continue
        rets = [0.0] + [
            (bars[k].close - bars[k - 1].close) / bars[k - 1].close if bars[k - 1].close > 0 else 0.0
            for k in range(1, len(bars))
        ]
        pr = rets[i - 36 : i]
        pv = [x.volume for x in bars[i - 36 : i]]
        ph = [x.high for x in bars[i - 72 : i]]
        mr = sum(pr) / len(pr)
        sr = math.sqrt(sum((r - mr) ** 2 for r in pr) / max(1, len(pr) - 1))
        mv = median(pv)
        z = (rets[i] - mr) / max(sr, 1e-4)
        if z < 3.0 or mv <= 0 or b.volume < 2.5 * mv or b.close <= max(ph):
            continue

        seq = []
        for j in range(i - 35, i + 1):
            bj = bars[j]
            rj = rets[j]
            hl = (bj.high - bj.low) / max(bj.close, 1e-9)
            vr = math.log1p(bj.volume / max(mv, 1e-9))
            rel_btc = rj - btc_ret.get(bj.ts_avail, 0.0)
            br_d = daily_breadth.get(bj.ts_avail.date().isoformat(), 0.5)
            seq.append([rj / max(sr, 1e-4), hl, vr, rel_btc, br_d, 1.0 if bj.close > bj.open else -1.0])
        p_win = float(model.predict(np.asarray([seq], dtype=np.float64))[0])
        if p_win >= base_prob + 0.05:
            lev, col_f = 1.5, 0.30
        elif p_win >= base_prob - 0.05:
            lev, col_f = 1.0, 0.30
        else:
            lev, col_f = 1.0, 0.15
        triggers.append({
            "symbol": sym,
            "bar_ts_avail": b.ts_avail.isoformat(),
            "z_score": round(z, 2),
            "gru_prob": round(p_win, 4),
            "leverage": lev,
            "slot_weight": round(col_f * lev, 4),
        })

    triggers.sort(key=lambda x: (-x["gru_prob"], -x["z_score"], x["symbol"]))
    ign_weights = {t["symbol"]: t["slot_weight"] for t in triggers[:3]}
    return latest_ts, triggers[:3], ign_weights


def append_jsonl_locked(journal_path: Path, record: dict, *, timeout_s: float = 5.0) -> bool:
    """Append one JSONL record under an exclusive sidecar lockfile with atomic slot_key deduplication.

    Returns True if appended, False if an identical slot_key already existed in the journal.
    """
    import time

    journal_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = journal_path.with_suffix(journal_path.suffix + ".lock")
    deadline = time.monotonic() + timeout_s
    fd: int | None = None
    while fd is None:
        try:
            fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            if time.monotonic() >= deadline:
                raise TimeoutError(f"could not acquire journal lock {lock_path}") from None
            time.sleep(0.05)
    try:
        slot_key = record.get("slot_key")
        if slot_key is not None and journal_path.is_file():
            for ln in journal_path.read_text(encoding="utf-8").splitlines():
                if ln.strip() and json.loads(ln).get("slot_key") == slot_key:
                    return False
        with journal_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, sort_keys=True) + "\n")
            fh.flush()
            os.fsync(fh.fileno())
        return True
    finally:
        os.close(fd)
        try:
            lock_path.unlink(missing_ok=True)
        except OSError:
            pass


def write_json_atomic(path: Path, payload: dict) -> None:
    """Atomically write JSON via temp file + fsync + os.replace so readers never see partial writes."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + f".tmp.{os.getpid()}")
    with tmp.open("w", encoding="utf-8") as fh:
        fh.write(json.dumps(payload, indent=2, sort_keys=True) + "\n")
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)


def _load_last_journal_state(journal_path: Path) -> tuple[set[str], dict[str, float]]:
    if not journal_path.is_file():
        return set(), {}
    seen_slots: set[str] = set()
    last_weights: dict[str, float] = {}
    for ln in journal_path.read_text(encoding="utf-8").splitlines():
        if not ln.strip():
            continue
        item = json.loads(ln)
        if item.get("slot_key"):
            seen_slots.add(str(item["slot_key"]))
        if isinstance(item.get("slow_weights"), dict):
            last_weights = {k: float(v) for k, v in item["slow_weights"].items()}
    return seen_slots, last_weights


def record_champion_ensemble_journal(
    db_path: Path,
    journal_path: Path,
    model_path: Path,
    *,
    multi_venue_db: Path | None = None,
    registration_path: Path | None = None,
    gold_symbol: str = "XAUTUSDT",
    slow_weight: float = 0.70,
    ignition_weight: float = 0.30,
    as_of: datetime | None = None,
) -> dict:
    """Record an idempotent live shadow snapshot of the Champion Ensemble (Slow Core + 2h GRU-Ignition)."""
    if journal_path.name == "mix-journal.jsonl":
        raise ValueError("refusing to touch v1 control mix-journal.jsonl")
    now = as_of or datetime.now(UTC)
    if not model_path.is_file():
        train_and_freeze_gru_ignition(db_path, model_path, as_of=now, gold_symbol=gold_symbol)

    model, model_meta = EnsembleGRU.load_json(model_path)
    model_sha = hashlib.sha256(model_path.read_bytes()).hexdigest()
    base_prob = float(model_meta.get("base_win_rate", 0.45))
    slow_syms = tuple(gold_symbol if s == "XAUTUSDT" else s for s in BASE_13_SYMBOLS)
    all_syms = tuple(dict.fromkeys(slow_syms + IGNITION_18_CRYPTO))

    engine_digest = _package_engine_digest()
    if registration_path is not None and registration_path.exists():
        existing_reg = json.loads(registration_path.read_text(encoding="utf-8"))
        reg_sha = existing_reg.get("gru_model_sha256")
        if reg_sha and reg_sha != model_sha:
            raise ValueError(f"model sha256 mismatch vs registration: {model_sha} != {reg_sha}")
    elif registration_path is not None and not registration_path.exists():
        reg = {
            "schema": "prospective-champion-registration/1",
            "strategy_id": f"CHAMPION_70_S1S5_{gold_symbol}_30_GRU_IGN18_2H",
            "registered_at": now.isoformat(),
            "selection_end": now.date().isoformat() + "T00:00:00+00:00",
            "engine_digest": engine_digest,
            "gru_model_path": str(model_path),
            "gru_model_sha256": model_sha,
            "gru_model_meta": model_meta,
            "slow_weight": slow_weight,
            "ignition_weight": ignition_weight,
            "slow_universe": list(slow_syms),
            "ignition_universe": list(IGNITION_18_CRYPTO),
            "execution_policy": "SIDE_ASYMMETRIC_ROUTER (Nobitex -30% primary, passive BUY / smart-taker SELL)",
            "funded_authority": False,
            "executor_state": "DISARMED",
        }
        registration_path.parent.mkdir(parents=True, exist_ok=True)
        registration_path.write_text(json.dumps(reg, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    seen_slots, prev_slow = _load_last_journal_state(journal_path)
    con = open_readonly_market_db(db_path)
    try:
        panel_1d = {s: load_keyed_candles(con, s, "1d", limit=400, as_of=now) for s in slow_syms}
        sigs_1d = compute_slow_sleeves(panel_1d, slow_syms, gold_symbol=gold_symbol)
        dated_rets = build_dated_returns_index(panel_1d, slow_syms)
        elig_dates = sorted(ts for ts, d in sigs_1d.items() if any(s.eligible_for_entry for s in d.values()))
        if not elig_dates:
            return {"status": "INSUFFICIENT_CANDLES", "as_of": now.isoformat()}
        latest_1d = elig_dates[-1]
        day_sigs = sigs_1d[latest_1d]
        active_slow = tuple(s for s in slow_syms if s in day_sigs)

        cov_h = build_shrunk_horizon_cov(dated_rets, active_slow, latest_1d)
        solved_slow = solve_s1_s5_admm_weights(
            active_slow, day_sigs, tuple(prev_slow.get(s, 0.0) for s in active_slow), cov_h,
        )
        slow_weights = {s: round(w, 4) for s, w in zip(active_slow, solved_slow, strict=True)}
        daily_breadth = extract_daily_breadth(sigs_1d)

        panel_2h = load_stitched_2h_panel(con, IGNITION_18_CRYPTO, as_of=now)
        latest_2h, ign_triggers, ign_weights = _score_live_2h_ignition(panel_2h, daily_breadth, model, base_prob)
        quotes = _latest_live_quotes(con, multi_venue_db, all_syms, as_of=now)
    finally:
        con.close()

    slot_ts = latest_2h or latest_1d
    slot_key = f"{now.date().isoformat()}|{slot_ts.isoformat()}"
    if slot_key in seen_slots:
        return {"status": "ALREADY_RECORDED", "slot_key": slot_key, "as_of": now.isoformat()}

    blended: dict[str, float] = {}
    for sym in all_syms:
        w = slow_weight * slow_weights.get(sym, 0.0) + ignition_weight * ign_weights.get(sym, 0.0)
        if w > 0.0005:
            blended[sym] = round(min(0.40, w), 4)
    gross = sum(blended.values())
    if gross > 1.10:
        sc = 1.10 / gross
        blended = {k: round(v * sc, 4) for k, v in blended.items()}

    record = {
        "schema": "champion-forward-journal/1",
        "slot_key": slot_key,
        "as_of": now.isoformat(),
        "signal_1d_bar": latest_1d.isoformat(),
        "signal_2h_bar": latest_2h.isoformat() if latest_2h else None,
        "daily_breadth": round(daily_breadth.get(latest_1d.date().isoformat(), 0.0), 4),
        "gold_symbol": gold_symbol,
        "slow_weights": slow_weights,
        "ignition_triggers": ign_triggers,
        "blended_weights": blended,
        "cash_weight": round(max(0.0, 1.0 - sum(blended.values())), 4),
        "live_quotes": {k: quotes[k] for k in sorted(set(blended) | {"BTCUSDT", "ETHUSDT", gold_symbol}) if k in quotes},
        "gru_model_sha256": model_sha,
        "engine_digest": engine_digest,
        "executor_state": "DISARMED",
    }

    append_jsonl_locked(journal_path, record)

    return {"status": "RECORDED", **record}


def _resolve_event_prices(
    rec: dict,
    bar_marks: dict[str, list[tuple[datetime, float]]],
    ev_ts: datetime,
) -> dict[str, float]:
    """Resolve strictly causal prices at ev_ts (live_quotes if present, else latest closed bar ts_avail <= ev_ts)."""
    from bisect import bisect_right

    px: dict[str, float] = {}
    for sym, q in (rec.get("live_quotes") or {}).items():
        val = q.get("nobitex_mid") or q.get("wallex_mid")
        if val is not None and float(val) > 0:
            px[sym] = float(val)
    for sym, series in bar_marks.items():
        if sym in px or not series:
            continue
        ts_only = [t for t, _ in series]
        pos = bisect_right(ts_only, ev_ts) - 1
        if pos >= 0:
            px[sym] = series[pos][1]
    return px


def _rebalance_forward_event(
    cash: float,
    units: dict[str, float],
    targets: dict[str, float],
    px_map: dict[str, float],
    nav: float,
    leg_fee_bps: float,
    unpriced: set[str],
) -> tuple[float, float, int]:
    """Order-invariant two-pass event rebalance: sells release cash first, then buys allocate from available cash."""
    fees_paid = 0.0
    fills = 0
    fee_r = leg_fee_bps / 10_000.0
    buy_requests: list[tuple[str, float, float]] = []

    # Pass 1: execute all sells/reductions first so ticker spelling never blocks cash availability.
    for sym in sorted(set(units) | set(targets)):
        tgt_val = max(0.0, targets.get(sym, 0.0)) * nav
        cur_u = units.get(sym, 0.0)
        px = px_map.get(sym)
        if px is None or px <= 0:
            if tgt_val > 0 or cur_u > 0:
                unpriced.add(sym)
            continue
        delta = tgt_val - (cur_u * px)
        if abs(delta) < 1e-6:
            continue
        if delta < 0:
            sell_val = min(cur_u * px, -delta)
            fee = sell_val * fee_r
            cash += max(0.0, sell_val - fee)
            rem_u = max(0.0, cur_u - (sell_val / px))
            if rem_u <= 1e-12:
                units.pop(sym, None)
            else:
                units[sym] = rem_u
            fees_paid += fee
            fills += 1
        else:
            buy_requests.append((sym, delta, px))

    # Pass 2: execute all buys proportionally to available cash (completely invariant to symbol order).
    if buy_requests and cash > 1e-6:
        total_req_with_fee = sum(d * (1.0 + fee_r) for _, d, _ in buy_requests)
        scale = min(1.0, cash / total_req_with_fee) if total_req_with_fee > 0 else 0.0
        for sym, delta, px in buy_requests:
            gross_spend = delta * (1.0 + fee_r) * scale
            if gross_spend <= 1e-6 or gross_spend > cash + 1e-9:
                continue
            actual_spend = min(gross_spend, cash)
            bought_val = actual_spend / (1.0 + fee_r)
            fee = actual_spend - bought_val
            cash -= actual_spend
            units[sym] = units.get(sym, 0.0) + (bought_val / px)
            fees_paid += fee
            fills += 1

    return cash, fees_paid, fills


def score_champion_forward_journal(journal_path: Path, db_path: Path, *, leg_fee_bps: float = 0.0) -> dict:
    """Event-by-event forward shadow account: deduplicates slots, never credits pre-entry moves, tracks unpriced symbols."""
    if not journal_path.is_file():
        return {"status": "NO_JOURNAL", "observations": 0, "paper_nav": 1000.0, "e_process": 1.0}
    raw_rows = [json.loads(ln) for ln in journal_path.read_text(encoding="utf-8").splitlines() if ln.strip()]
    if not raw_rows:
        return {"status": "EMPTY_JOURNAL", "observations": 0, "paper_nav": 1000.0, "e_process": 1.0}

    # Chronological event stream deduplicated by slot_key (replaying a decision twice posts once).
    seen_slots: set[str] = set()
    events: list[tuple[datetime, dict]] = []
    for r in sorted(raw_rows, key=lambda x: parse_ts(x["as_of"])):
        sk = r.get("slot_key")
        if sk is not None:
            if sk in seen_slots:
                continue
            seen_slots.add(str(sk))
        events.append((parse_ts(r["as_of"]), r))

    nbx_spreads, wlx_spreads = [], []
    for _, r in events:
        for q in (r.get("live_quotes") or {}).values():
            if "nobitex_spread_bps" in q:
                nbx_spreads.append(float(q["nobitex_spread_bps"]))
            if "wallex_spread_bps" in q:
                wlx_spreads.append(float(q["wallex_spread_bps"]))

    all_syms = sorted({s for _, r in events for s in (r.get("blended_weights") or {})})
    bar_marks: dict[str, list[tuple[datetime, float]]] = {}
    if len(events) >= 2 and all_syms and db_path.is_file():
        con = open_readonly_market_db(db_path)
        try:
            since_iso = (events[0][0] - timedelta(days=2)).isoformat()
            for sym in all_syms:
                bars = load_keyed_candles(con, sym, "1d", limit=5000, since_iso=since_iso)
                bar_marks[sym] = [(b.ts_avail, b.close) for b in bars if b.close > 0]
        finally:
            con.close()

    cash = 1000.0
    units: dict[str, float] = {}
    last_known_px: dict[str, float] = {}
    unpriced: set[str] = set()
    fills = 0
    total_fees = 0.0
    nav = 1000.0
    peak_nav = 1000.0
    e_val = 1.0
    prev_day: str | None = None
    prev_day_nav = 1000.0

    for ev_ts, rec in events:
        px_map = _resolve_event_prices(rec, bar_marks, ev_ts)
        last_known_px.update(px_map)
        # Mark existing holdings at current event prices before rebalancing (pre-entry moves earn $0).
        nav = cash + sum(u * last_known_px[s] for s, u in units.items() if s in last_known_px)
        unpriced.update(s for s, u in units.items() if u > 0 and s not in last_known_px)
        peak_nav = max(peak_nav, nav)

        day_str = ev_ts.date().isoformat()
        if prev_day is not None and day_str != prev_day and prev_day_nav > 0:
            day_ret = (nav / prev_day_nav) - 1.0
            e_val *= max(0.0, 1.0 + 0.5 * max(-1.0, day_ret))
            prev_day_nav = nav
        elif prev_day is None:
            prev_day_nav = nav
        prev_day = day_str

        # Rebalance to event target weights strictly at current event price (never backward).
        targets = {s: float(w) for s, w in (rec.get("blended_weights") or {}).items()}
        cash, ev_fees, ev_fills = _rebalance_forward_event(cash, units, targets, px_map, nav, leg_fee_bps, unpriced)
        total_fees += ev_fees
        fills += ev_fills

    days = sorted({ts.date().isoformat() for ts, _ in events})
    latest_rec = events[-1][1]
    return {
        "status": "TRACKING",
        "observations": len(raw_rows),
        "unique_slots": len(events),
        "forward_days": len(days),
        "first_day": days[0],
        "latest_day": days[-1],
        "paper_nav": round(nav, 2),
        "peak_nav": round(peak_nav, 2),
        "cum_ret_pct": round((nav / 1000.0 - 1.0) * 100.0, 2),
        "e_process": round(e_val, 4),
        "fills": fills,
        "total_fees_usdt": round(total_fees, 2),
        "unpriced_symbols": sorted(unpriced),
        "latest_cash_weight": latest_rec.get("cash_weight", 1.0),
        "latest_blended_weights": latest_rec.get("blended_weights", {}),
        "latest_ignition_triggers": latest_rec.get("ignition_triggers", []),
        "median_live_nobitex_spread_bps": round(median(nbx_spreads), 2) if nbx_spreads else None,
        "median_live_wallex_spread_bps": round(median(wlx_spreads), 2) if wlx_spreads else None,
        "backtest_assumption_nbx_allin_bps": 16.0,
        "backtest_assumption_wlx_allin_bps": 25.0,
    }
