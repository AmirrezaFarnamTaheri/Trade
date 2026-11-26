"""Prospective live forward shadow journal for the v2 Champion Ensemble (parallel to frozen v1 Champion).

Combines strictly verified v2 winners:
- 1d Core: BASE_13_S1_S5 (XAUT) + ACCEL_BLEND_20 + 11A Multi-Issuer Metals Reserve (XAUT/PAXG/SLVON)
- 2h Ignition: 50/50 Phase-Invariant Twin Book (0h + 1h) + Frozen 11-feat Coiled-Spring Path-PnL GRU + Conformal/DD Governor
- Portfolio & Execution: Joint Single-ADMM Cross-Sleeve Netting + Live Nobitex<->Wallex Entry Guard & Exit Rebate telemetry
Read-only against market.db / multi_venue_quotes.sqlite3; DISARMED; never touches v1 mix-journal.jsonl or v1 champion journal.
"""
from __future__ import annotations

import hashlib
import json
import math
from datetime import UTC, datetime, timedelta
from pathlib import Path
from statistics import median

import numpy as np

from ...adapters.candle_reader import load_keyed_candles, open_readonly_market_db
from ...domain.convex_optimizer import (
    OptimizationProblem,
    forecast_to_expected_return_bps,
    solve_convex_portfolio,
)
from ...domain.core_signal_geometry import (
    DEFENSIVE_METALS_CAPS,
    compute_defensive_metals_reserve,
)
from ...domain.diffusion_and_netting import _build_cluster_groups
from ...domain.higher_order_and_sparse import compute_second_order_trend_map
from ...domain.ignition_upgrades import (
    _select_lev_and_col,
    compute_cross_sectional_2h_context,
)
from ...domain.multi_asset_research import BASE_13_SYMBOLS
from ...domain.strategy_sleeves import compute_slow_sleeves
from ...domain.timeframe_panel import BarPoint, resample_hourly_to_bucket
from ...domain.venue_leverage_models import NOBITEX_MARGIN_ELIGIBLE_USDT
from .admm_helpers import (
    build_dated_returns_index,
    build_shrunk_horizon_cov,
    extract_daily_breadth,
)
from .champion_forward_journal import (
    _latest_live_quotes,
    append_jsonl_locked,
    compute_cohort_id,
    iter_valid_jsonl_records,
    load_stitched_1h_panel,
    readonly_snapshot,
    score_champion_forward_journal,
    write_json_atomic,
)
from .gru_engine import EnsembleGRU
from .ignition_expansion_study import IGNITION_18_CRYPTO
from .ignition_upgrade_ablation_study import _extract_11feat_coiled_spring_dataset
from .leader_forward_journal import _package_engine_digest


def _resample_2h_phase_closed(
    panel_1h: dict[str, list[BarPoint]],
    *,
    offset_hours: int,
    as_of: datetime | None = None,
) -> dict[str, list[BarPoint]]:
    out: dict[str, list[BarPoint]] = {}
    for sym, merged in panel_1h.items():
        bars_2h = resample_hourly_to_bucket(merged, 2, offset_hours=offset_hours) if merged else []
        if as_of is not None:
            bars_2h = [b for b in bars_2h if b.ts_avail <= as_of and b.clock_complete]
        out[sym] = bars_2h
    return out


def train_and_freeze_v2_gru(db_path: Path, model_path: Path, *, as_of: datetime | None = None) -> dict:
    """Train & freeze 11-feature Coiled-Spring 3-seed EnsembleGRU on exact path-dependent net trade P&L."""
    cutoff = as_of or datetime.now(UTC)
    purge_cutoff = cutoff - timedelta(hours=48)
    con = open_readonly_market_db(db_path)
    try:
        panel_13 = {s: load_keyed_candles(con, s, "1d", limit=2500) for s in BASE_13_SYMBOLS}
        panel_1h = {s: load_keyed_candles(con, s, "1h", limit=26000) for s in IGNITION_18_CRYPTO}
    finally:
        con.close()

    sigs_13 = compute_slow_sleeves(panel_13, BASE_13_SYMBOLS)
    daily_breadth = extract_daily_breadth(sigs_13)
    p2h_0 = {s: resample_hourly_to_bucket(panel_1h[s], 2, offset_hours=0) for s in IGNITION_18_CRYPTO}
    dts, _, xs11, _, y_path = _extract_11feat_coiled_spring_dataset(p2h_0, IGNITION_18_CRYPTO, daily_breadth)
    keep = [k for k, dt in enumerate(dts) if dt < purge_cutoff]
    if len(keep) < 80:
        raise RuntimeError(f"Insufficient pre-cutoff episodes ({len(keep)}) to train v2 GRU")

    x_tr, y_tr = xs11[keep], y_path[keep]
    model = EnsembleGRU(input_dim=11, hidden_dim=12, task="regression", seeds=(42, 101, 202))
    model.fit(x_tr, y_tr, epochs=24, batch_size=64, lr=4e-3, l2_reg=5e-3)
    recent_preds = [round(float(v), 5) for v in model.predict(x_tr[-100:])]

    meta = {
        "model_id": "GRU_IGNITION_11FEAT_PATHPNL_V2",
        "trained_at": cutoff.isoformat(),
        "purge_cutoff_utc": purge_cutoff.isoformat(),
        "episodes": len(keep),
        "task": "regression_exact_path_pnl",
        "seq_len": 36,
        "seed_conformal_scores": recent_preds,
        "symbols": list(IGNITION_18_CRYPTO),
    }
    model.save_json(model_path, metadata=meta)
    raw = model_path.read_bytes()
    return {"model_path": str(model_path), "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest(), "metadata": meta}


def _score_phase_v2_triggers(
    panel_2h: dict[str, list[BarPoint]],
    daily_breadth: dict[str, float],
    model: EnsembleGRU,
    recent_scores: list[float],
    in_dd_throttle: bool,
    *,
    phase_tag: str,
) -> tuple[datetime | None, list[dict], dict[str, float]]:
    wave_by_ts, rank_by_ts_sym = compute_cross_sectional_2h_context(panel_2h, IGNITION_18_CRYPTO)
    btc_bars = panel_2h.get("BTCUSDT", [])
    btc_ret = {
        btc_bars[i].ts_avail: (btc_bars[i].close - btc_bars[i - 1].close) / btc_bars[i - 1].close
        for i in range(1, len(btc_bars)) if btc_bars[i - 1].close > 0
    }
    af, as_ = 2.0 / 5.0, 2.0 / 13.0
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
        if daily_breadth.get(b.ts_avail.date().isoformat(), 0.0) < 0.45:
            continue
        rets = [0.0] + [(bars[k].close - bars[k - 1].close) / bars[k - 1].close if bars[k - 1].close > 0 else 0.0 for k in range(1, len(bars))]
        hls = [(x.high - x.low) / max(x.close, 1e-9) for x in bars]
        pr, pv, ph = rets[i - 36 : i], [x.volume for x in bars[i - 36 : i]], [x.high for x in bars[i - 72 : i]]
        mr = sum(pr) / 36.0
        sr = math.sqrt(sum((r - mr) ** 2 for r in pr) / 35.0)
        mv = median(pv)
        z = (rets[i] - mr) / max(sr, 1e-4)
        if z < 3.0 or mv <= 0 or b.volume < 2.5 * mv or b.close <= max(ph):
            continue

        seq = []
        ef_r, es_r, ef_v, es_v = 0.0, 0.0, 0.0, 0.0
        for idx_j, j in enumerate(range(i - 35, i + 1)):
            bj, rj = bars[j], rets[j]
            zr = rj / max(sr, 1e-4)
            vr = math.log1p(bj.volume / max(mv, 1e-9))
            if idx_j == 0:
                ef_r, es_r, ef_v, es_v = zr, zr, vr, vr
            else:
                ef_r, es_r = (1.0 - af) * ef_r + af * zr, (1.0 - as_) * es_r + as_ * zr
                ef_v, es_v = (1.0 - af) * ef_v + af * vr, (1.0 - as_) * es_v + as_ * vr
            hl_12 = sum(hls[max(0, j - 5) : j + 1]) / max(1, min(6, j + 1))
            hl_72 = sum(hls[max(0, j - 35) : j + 1]) / max(1, min(36, j + 1))
            seq.append([
                zr, hls[j], vr, rj - btc_ret.get(bj.ts_avail, 0.0),
                daily_breadth.get(bj.ts_avail.date().isoformat(), 0.5),
                1.0 if bj.close > bj.open else -1.0, ef_r - es_r, ef_v - es_v,
                min(3.0, hl_12 / max(hl_72, 1e-4)), wave_by_ts.get(bj.ts_avail, 0.0),
                rank_by_ts_sym.get((bj.ts_avail, sym), 0.5),
            ])
        pred_ret = float(model.predict(np.asarray([seq], dtype=np.float64))[0])
        lev, col_f = _select_lev_and_col(
            pred_ret, score_is_return=True, base_prob=0.0, use_conformal=True,
            recent_scores=recent_scores, in_dd_throttle=in_dd_throttle,
        )
        triggers.append({
            "phase": phase_tag, "symbol": sym, "bar_ts_avail": b.ts_avail.isoformat(),
            "z_score": round(z, 2), "pred_path_pnl": round(pred_ret, 5),
            "leverage": lev, "slot_weight": round(col_f * lev, 4),
        })

    triggers.sort(key=lambda x: (-x["pred_path_pnl"], -x["z_score"], x["symbol"]))
    return latest_ts, triggers[:3], {t["symbol"]: t["slot_weight"] for t in triggers[:3]}


def _latest_nobitex_usdt_pool_apr(multi_venue_db: Path | None) -> float | None:
    if multi_venue_db is None or not multi_venue_db.is_file():
        return None
    con = open_readonly_market_db(multi_venue_db)
    try:
        has_tbl = con.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='venue_liquidity_pools'"
        ).fetchone()
        if not has_tbl:
            return None
        row = con.execute(
            "SELECT apr_pct FROM venue_liquidity_pools WHERE venue='nobitex' AND currency='USDT' ORDER BY id DESC LIMIT 1"
        ).fetchone()
        return float(row[0]) if (row and row[0]) else None
    finally:
        con.close()


def _load_v2_state(journal_path: Path) -> tuple[set[str], dict[str, float], list[float]]:
    rows, _ = iter_valid_jsonl_records(journal_path)
    seen, last_w, scores = set(), {}, []
    for item in rows:
        if item.get("slot_key"):
            seen.add(str(item["slot_key"]))
        if isinstance(item.get("blended_weights"), dict):
            last_w = {k: float(v) for k, v in item["blended_weights"].items()}
        for trig in item.get("ignition_triggers") or []:
            if "pred_path_pnl" in trig:
                scores.append(float(trig["pred_path_pnl"]))
    return seen, last_w, scores[-100:]


def record_champion_v2_journal(
    db_path: Path,
    journal_path: Path,
    model_path: Path,
    *,
    multi_venue_db: Path | None = None,
    registration_path: Path | None = None,
    slow_weight: float = 0.70,
    ignition_weight: float = 0.30,
    as_of: datetime | None = None,
) -> dict:
    """Record an idempotent live shadow snapshot of the Unified v2 Champion Ensemble (parallel to v1)."""
    if journal_path.name in ("mix-journal.jsonl", "champion-ensemble-journal.jsonl"):
        raise ValueError(f"refusing to touch protected journal {journal_path.name}")
    now = as_of or datetime.now(UTC)
    if not model_path.is_file():
        train_and_freeze_v2_gru(db_path, model_path, as_of=now)

    model, meta = EnsembleGRU.load_json(model_path)
    model_sha = hashlib.sha256(model_path.read_bytes()).hexdigest()
    engine_digest = _package_engine_digest()
    cohort_id = compute_cohort_id("champion-v2-forward-journal/1", model_sha, engine_digest, slow_weight, ignition_weight)
    all_syms = tuple(dict.fromkeys(BASE_13_SYMBOLS + IGNITION_18_CRYPTO + tuple(DEFENSIVE_METALS_CAPS)))
    reg_engine_drift = False

    if registration_path is not None and registration_path.exists():
        existing_reg = json.loads(registration_path.read_text(encoding="utf-8"))
        reg_sha = existing_reg.get("gru_model_sha256")
        if reg_sha and reg_sha != model_sha:
            raise ValueError(f"v2 model sha256 mismatch vs registration: {model_sha} != {reg_sha}")
        reg_digest = existing_reg.get("engine_digest")
        if reg_digest and reg_digest != engine_digest:
            reg_engine_drift = True
    elif registration_path is not None and not registration_path.exists():
        reg = {
            "schema": "prospective-champion-v2-registration/1",
            "strategy_id": "CHAMPION_V2_70_ACCEL_METALS_30_TWIN_GRU11_PATHPNL_CONFORMAL_JOINT_ADMM",
            "registered_at": now.isoformat(),
            "selection_end": now.date().isoformat() + "T00:00:00+00:00",
            "engine_digest": engine_digest,
            "cohort_id": cohort_id,
            "gru_model_path": str(model_path),
            "gru_model_sha256": model_sha,
            "slow_weight": slow_weight,
            "ignition_weight": ignition_weight,
            "components": [
                "1d BASE_13_S1_S5 (XAUT) + ACCEL_BLEND_20",
                "1d 11A Multi-Issuer Metals Reserve (XAUT<=25%, PAXG<=15%, SLVON<=10%)",
                "2h 50/50 Twin-Phase (0h + 1h) IGN18 + 11-feat Coiled-Spring GRU (Exact Path-PnL)",
                "Conformal Top-33% Rank Gate + 5% Equity-Curve DD Leverage Governor",
                "Joint Single-ADMM Cross-Sleeve Netting & 40% Sector Cluster Caps",
                "Live Nobitex<->Wallex Fair-Value Entry Guard & Exit Rebate Telemetry",
            ],
            "funded_authority": False,
            "executor_state": "DISARMED",
        }
        write_json_atomic(registration_path, reg)

    seen_slots, prev_blended, live_scores = _load_v2_state(journal_path)
    seed_scores = [float(x) for x in (meta.get("seed_conformal_scores") or [])]
    conformal_hist = (seed_scores + live_scores)[-100:]
    prev_score = score_champion_forward_journal(journal_path, db_path) if journal_path.is_file() else {"paper_nav": 1000.0, "peak_nav": 1000.0}
    cur_nav = float(prev_score.get("paper_nav", 1000.0))
    peak_nav = float(prev_score.get("peak_nav", max(1000.0, cur_nav)))
    in_dd = peak_nav > 0.0 and ((peak_nav - cur_nav) / peak_nav >= 0.05)

    con = open_readonly_market_db(db_path)
    try:
        with readonly_snapshot(con):
            # Load 1h+tail-1min ONCE for both phases and enforce strict closed-bar watermark <= now.
            panel_1h_ign = load_stitched_1h_panel(con, IGNITION_18_CRYPTO, as_of=now)
            p2h_0 = _resample_2h_phase_closed(panel_1h_ign, offset_hours=0, as_of=now)
            p2h_1 = _resample_2h_phase_closed(panel_1h_ign, offset_hours=1, as_of=now)
            max_2h = max(
                (bars[-1].ts_avail for p in (p2h_0, p2h_1) for bars in p.values() if bars),
                default=None,
            )
            if max_2h is not None:
                early_slot = f"{now.date().isoformat()}|{max_2h.isoformat()}"
                if early_slot in seen_slots:
                    return {"status": "ALREADY_RECORDED", "slot_key": early_slot, "as_of": now.isoformat()}

            panel_13 = {s: load_keyed_candles(con, s, "1d", limit=400, as_of=now) for s in BASE_13_SYMBOLS}
            panel_metals = {s: load_keyed_candles(con, s, "1d", limit=400, as_of=now) for s in DEFENSIVE_METALS_CAPS}
            sigs_13 = compute_slow_sleeves(panel_13, BASE_13_SYMBOLS)
            accel_13 = compute_second_order_trend_map(sigs_13, BASE_13_SYMBOLS)
            sigs_metals = compute_slow_sleeves(panel_metals, tuple(DEFENSIVE_METALS_CAPS), min_active_crypto=1, warmup_bars=64)
            elig = sorted(ts for ts, d in sigs_13.items() if any(s.eligible_for_entry for s in d.values()))
            if not elig:
                return {"status": "INSUFFICIENT_CANDLES", "as_of": now.isoformat()}
            latest_1d = elig[-1]
            daily_breadth = extract_daily_breadth(sigs_13)

            ts0, trig0, iw0 = _score_phase_v2_triggers(p2h_0, daily_breadth, model, conformal_hist, in_dd, phase_tag="0h")
            ts1, trig1, iw1 = _score_phase_v2_triggers(p2h_1, daily_breadth, model, conformal_hist, in_dd, phase_tag="1h")
            ign_w = {s: 0.5 * iw0.get(s, 0.0) + 0.5 * iw1.get(s, 0.0) for s in set(iw0) | set(iw1)}

            day_sigs = sigs_13[latest_1d]
            day_acc = accel_13.get(latest_1d, {})
            active_slow = tuple(s for s in BASE_13_SYMBOLS if s in day_sigs)
            dated_rets = build_dated_returns_index(panel_13, BASE_13_SYMBOLS)
            cov_h = build_shrunk_horizon_cov(dated_rets, active_slow, latest_1d)
            sqrt_h = math.sqrt(20.0)
            mu_gross = []
            for sym in active_slow:
                sig = day_sigs[sym]
                s1_v = max(-1.0, min(1.0, 0.80 * sig.s1_trend + 0.20 * day_acc.get(sym, 0.0))) if sig.s1_trend is not None else None
                parts = [v for v in (s1_v, sig.s5_defensive_gold) if v is not None]
                raw = sum(parts) / len(parts) if parts else 0.0
                mu_gross.append(
                    forecast_to_expected_return_bps(raw * 20.0, ic_prior=0.08, horizon_vol_bps=sig.yang_zhang_vol * sqrt_h * 10000.0) / 10000.0
                )
            reserved_ign = min(0.45, sum(ignition_weight * v for v in ign_w.values()))
            adj_cur = tuple(max(0.0, (prev_blended.get(s, 0.0) - ignition_weight * ign_w.get(s, 0.0)) / max(slow_weight, 1e-6)) for s in active_slow)
            prob = OptimizationProblem(
                symbols=active_slow, expected_returns=tuple(mu_gross), current_weights=adj_cur,
                covariance=cov_h, l1_fee_costs=(0.0013,) * len(active_slow), l2_impact_costs=(0.0020,) * len(active_slow),
                risk_aversion=2.0, max_weight=0.30, cash_buffer=0.05, reserved_open_weight=max(0.0, reserved_ign * 0.5),
                underlying_groups=_build_cluster_groups(active_slow), max_underlying_weight=0.40,
            )
            slow_w = {s: round(w, 4) for s, w in zip(active_slow, solve_convex_portfolio(prob).weights, strict=True)}
            day_br = daily_breadth.get(latest_1d.date().isoformat())
            res_m = compute_defensive_metals_reserve(sigs_metals.get(latest_1d, {}), day_br)
            free_c = max(0.0, 0.95 - sum(slow_w.values()))
            for ms, mw in res_m.items():
                if mw > 0:
                    take = min(max(0.0, mw - slow_w.get(ms, 0.0)), free_c)
                    slow_w[ms] = round(slow_w.get(ms, 0.0) + take, 4)
                    free_c -= take

            quotes = _latest_live_quotes(con, multi_venue_db, all_syms, as_of=now)
    finally:
        con.close()

    latest_2h = max((t for t in (ts0, ts1) if t is not None), default=latest_1d)
    slot_key = f"{now.date().isoformat()}|{latest_2h.isoformat()}"
    if slot_key in seen_slots:
        return {"status": "ALREADY_RECORDED", "slot_key": slot_key, "as_of": now.isoformat()}

    blended = {
        s: round(min(0.40, slow_weight * slow_w.get(s, 0.0) + ignition_weight * ign_w.get(s, 0.0)), 4)
        for s in all_syms
        if slow_weight * slow_w.get(s, 0.0) + ignition_weight * ign_w.get(s, 0.0) > 0.0005
    }
    gross = sum(blended.values())
    if gross > 0.95 and gross > 0:
        sc = 0.95 / gross
        blended = {k: round(v * sc, 4) for k, v in blended.items()}

    all_trigs = trig0 + trig1
    nbx_2x_elig = [
        t["symbol"]
        for t in all_trigs
        if t.get("leverage", 1.0) > 1.0 and t.get("symbol") in NOBITEX_MARGIN_ELIGIBLE_USDT
    ]
    usdt_pool_apr = _latest_nobitex_usdt_pool_apr(multi_venue_db)

    record = {
        "schema": "champion-v2-forward-journal/1",
        "slot_key": slot_key,
        "as_of": now.isoformat(),
        "signal_1d_bar": latest_1d.isoformat(),
        "signal_2h_bar": latest_2h.isoformat(),
        "daily_breadth": round(day_br or 0.0, 4),
        "dd_leverage_governor_active": in_dd,
        "slow_weights": slow_w,
        "metals_reserve": {k: round(v, 4) for k, v in res_m.items() if v > 0},
        "ignition_triggers": all_trigs,
        "nobitex_margin_2x_eligible_triggers": sorted(set(nbx_2x_elig)),
        "live_idle_usdt_pool_apr_pct": usdt_pool_apr,
        "blended_weights": blended,
        "cash_weight": round(max(0.0, 1.0 - sum(blended.values())), 4),
        "live_quotes": {k: quotes[k] for k in sorted(set(blended) | {"BTCUSDT", "ETHUSDT", "XAUTUSDT", "PAXGUSDT"}) if k in quotes},
        "gru_model_sha256": model_sha,
        "engine_digest": engine_digest,
        "cohort_id": cohort_id,
        "registration_engine_drift": reg_engine_drift,
        "executor_state": "DISARMED",
    }
    append_jsonl_locked(journal_path, record)
    return {"status": "RECORDED", **record}
