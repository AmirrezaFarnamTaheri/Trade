"""Post-Repair Cross-Venue Clocks, Cadence, Blind Bake-Off & Cost Break-Even Study.

Implements the remaining four items from docs/architecture/2026-11-25-last-42-commits-review.md:
  - Idea 12: Cross-venue price discovery on receipt-time grid + artificial delay & swapped-label controls.
  - Idea 13: Event-driven vs. fixed-cadence engine scoring (CPU saved vs economic divergence).
  - Idea 14: Blind prospective paper bake-off registration (SHA-256 blinded labels + sealed key).
  - Review Priority #3 & F11: Cost/capacity break-even sweep (fees, borrow, missed fills) + SLOW_40PCT_PLUS_CASH control.

Strictly read-only against market.db / multi_venue_quotes.sqlite3; DISARMED ($0 funded budget).
"""
from __future__ import annotations

import hashlib
import json
import random
import secrets
import time
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from statistics import mean

from ...adapters.candle_reader import load_keyed_candles, open_readonly_market_db
from ...domain.multi_asset_research import BASE_13_SYMBOLS
from ...domain.paper_ledger import SelfFinancingLedger
from ...domain.short_and_levered_ignition import _breakdown_or_breakout_z
from ...domain.strategy_sleeves import compute_slow_sleeves
from ...domain.timeframe_panel import BarPoint, resample_hourly_to_bucket
from .admm_helpers import extract_daily_breadth
from .champion_v2_verification import _extract_daily_s1_s5_targets
from .ensemble_study import portfolio_metrics
from .ignition_expansion_study import IGNITION_18_CRYPTO
from .treasury_liquidity_and_fx_study import _load_matched_live_books
from .unified_book_helpers import resolve_bar_prices


def _lead_hit_rate(pairs: list[tuple[float, float]]) -> tuple[int, float, float]:
    """Return (eligible_count, directional hit rate %, mean predicted-direction return bps) for |basis| >= 5 bps."""
    valid = [(b, r) for b, r in pairs if abs(b) >= 5.0]
    if not valid:
        return 0, 0.0, 0.0
    hits = sum(1 for b, r in valid if (b > 0 and r > 0) or (b < 0 and r < 0))
    signed_bps = [r if b > 0 else -r for b, r in valid]
    return len(valid), round(hits / len(valid) * 100.0, 1), round(mean(signed_bps), 2)


def _run_idea_12_price_discovery(matched_books: dict[str, list[dict]]) -> list[dict]:
    """Idea 12: Test cross-venue lead/lag with +1-step artificial transport delay & swapped-label placebo."""
    rng = random.Random(42)
    rows = []
    for sym in ("BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT"):
        snaps = matched_books.get(sym, [])
        if len(snaps) < 20:
            continue
        wlx_leads_nbx, nbx_leads_wlx, delayed_wlx, placebo = [], [], [], []
        for i in range(1, len(snaps) - 1):
            m0, m1 = snaps[i], snaps[i + 1]
            dt_s = m1["epoch"] - m0["epoch"]
            if dt_s <= 0 or dt_s > 180.0:
                continue
            basis_w_minus_n = (m0["w_mid"] - m0["n_mid"]) / m0["n_mid"] * 10_000.0
            n_next_ret = (m1["n_mid"] - m0["n_mid"]) / m0["n_mid"] * 10_000.0
            w_next_ret = (m1["w_mid"] - m0["w_mid"]) / m0["w_mid"] * 10_000.0
            wlx_leads_nbx.append((basis_w_minus_n, n_next_ret))
            nbx_leads_wlx.append((-basis_w_minus_n, w_next_ret))
            # Artificial 1-snapshot transport delay on Wallex feed
            m_prev = snaps[i - 1]
            basis_delayed = (m_prev["w_mid"] - m0["n_mid"]) / m0["n_mid"] * 10_000.0
            delayed_wlx.append((basis_delayed, n_next_ret))
            # Swapped-label placebo
            sign = 1.0 if rng.random() < 0.5 else -1.0
            placebo.append((sign * basis_w_minus_n, n_next_ret))

        wn, wh, wb = _lead_hit_rate(wlx_leads_nbx)
        nn, nh, nb = _lead_hit_rate(nbx_leads_wlx)
        _, dh, db = _lead_hit_rate(delayed_wlx)
        _, ph, pb = _lead_hit_rate(placebo)
        rows.append({
            "symbol": sym,
            "total_samples": len(wlx_leads_nbx),
            "samples": wn,
            "eligible_samples": wn,
            "wlx_leads_nbx_hit_pct": wh,
            "wlx_leads_nbx_bps": wb,
            "nbx_leads_wlx_hit_pct": nh,
            "nbx_leads_wlx_bps": nb,
            "wlx_delayed_1step_bps": db,
            "swapped_placebo_bps": pb,
        })
    return rows


def _run_idea_13_event_vs_fixed_cadence(
    panel_2h: dict[str, list[BarPoint]],
    daily_breadth: dict[str, float],
) -> dict:
    """Idea 13: Benchmark two genuinely separate scheduler paths with process_time CPU, p95 latency & missed-trigger P&L."""
    by_avail = {s: {b.ts_avail: b for b in panel_2h.get(s, [])} for s in IGNITION_18_CRYPTO}
    by_start = {s: {b.ts_start: b for b in panel_2h.get(s, [])} for s in IGNITION_18_CRYPTO}
    all_ts = sorted({t for d in by_avail.values() for t in d})
    ts_pos = {t: i for i, t in enumerate(all_ts)}

    def _run_scheduler(*, event_gated: bool) -> tuple[int, list[tuple[datetime, str]], float, float]:
        ret_h: dict[str, list[float]] = {s: [] for s in IGNITION_18_CRYPTO}
        vol_h: dict[str, list[float]] = {s: [] for s in IGNITION_18_CRYPTO}
        high_h: dict[str, list[float]] = {s: [] for s in IGNITION_18_CRYPTO}
        low_h: dict[str, list[float]] = {s: [] for s in IGNITION_18_CRYPTO}
        prev_c: dict[str, float] = {}
        evals = 0
        bars_since = 0
        trigs: list[tuple[datetime, str]] = []
        bar_ms: list[float] = []
        cpu0 = time.process_time()

        for ts in all_ts:
            w0 = time.perf_counter()
            bars_since += 1
            cur_rets: dict[str, float] = {}
            material = (not event_gated) or (bars_since >= 12)
            for sym in IGNITION_18_CRYPTO:
                cur = by_avail[sym].get(ts)
                if cur is None or cur.close <= 0:
                    continue
                r = ((cur.close - prev_c[sym]) / prev_c[sym]) if (sym in prev_c and prev_c[sym] > 0) else 0.0
                cur_rets[sym] = r
                if event_gated and abs(r) >= 0.015:
                    material = True
            if material:
                evals += 1
                bars_since = 0
                if daily_breadth.get(ts.date().isoformat(), 0.0) >= 0.45:
                    for sym, r in cur_rets.items():
                        cur = by_avail[sym][ts]
                        if cur.entry_eligible:
                            hit = _breakdown_or_breakout_z(
                                cur, r, high_h[sym][-72:], low_h[sym][-72:], ret_h[sym][-36:], vol_h[sym][-36:],
                                side="LONG", breakout_bars=72, vol_lookback=36, z_threshold=3.0, vol_mult=2.5,
                            )
                            if hit is not None:
                                trigs.append((ts, sym))
            for sym, r in cur_rets.items():
                cur = by_avail[sym][ts]
                if sym in prev_c and prev_c[sym] > 0:
                    ret_h[sym].append(r)
                prev_c[sym] = cur.close
                vol_h[sym].append(cur.volume)
                high_h[sym].append(cur.high)
                low_h[sym].append(cur.low)
            bar_ms.append((time.perf_counter() - w0) * 1000.0)

        cpu_ms = (time.process_time() - cpu0) * 1000.0
        bar_ms.sort()
        p95 = bar_ms[int(0.95 * (len(bar_ms) - 1))] if bar_ms else 0.0
        return evals, trigs, cpu_ms, p95

    f_evals, f_trigs, f_cpu, f_p95 = _run_scheduler(event_gated=False)
    e_evals, e_trigs, e_cpu, e_p95 = _run_scheduler(event_gated=True)
    missed = sorted(set(f_trigs) - set(e_trigs))
    missed_pnls_bps: list[float] = []
    for ts, sym in missed:
        i0 = ts_pos.get(ts, 0)
        b0 = by_start[sym].get(ts)
        b12 = by_start[sym].get(all_ts[min(len(all_ts) - 1, i0 + 12)])
        if b0 and b12 and b0.open > 0:
            missed_pnls_bps.append(((b12.open - b0.open) / b0.open - 0.0032) * 10_000.0)

    return {
        "fixed_2h_evaluations": f_evals,
        "event_triggered_evaluations": e_evals,
        "cpu_evaluations_saved_pct": round((1.0 - e_evals / max(1, f_evals)) * 100.0, 1),
        "fixed_cpu_ms": round(f_cpu, 1),
        "event_cpu_ms": round(e_cpu, 1),
        "measured_cpu_saved_pct": round((1.0 - e_cpu / max(1e-6, f_cpu)) * 100.0, 1),
        "fixed_p95_bar_ms": round(f_p95, 4),
        "event_p95_bar_ms": round(e_p95, 4),
        "fixed_triggers": len(f_trigs),
        "event_triggers_captured": len(e_trigs),
        "trigger_capture_rate_pct": round(len(e_trigs) / max(1, len(f_trigs)) * 100.0, 2),
        "missed_trigger_count": len(missed),
        "missed_triggers_net_24h_bps": [round(x, 2) for x in missed_pnls_bps],
    }


def _run_idea_14_blind_bakeoff_manifest(sealed_key_path: Path, *, public_manifest_path: Path | None = None) -> dict:
    """Idea 14: Concealed-salt SHA-256 blinded bake-off; sealed key stays outside Git, public manifest has hashes only."""
    salt = secrets.token_hex(16)
    arms = (
        ("FIXED_S1_SLOW_SPOT_BENCHMARK", "baseline"),
        ("CHAMPION_V2_TWIN_GRU11", "challenger_a"),
        ("E3_V2_PLUS_BEAR50_UNIFIED", "challenger_b"),
        ("EXPOSURE_MATCHED_SHUFFLED_PLACEBO", "placebo"),
    )
    hashed = sorted(
        (hashlib.sha256(f"{salt}:{name}".encode()).hexdigest()[:12], name, role)
        for name, role in arms
    )
    aliases = [f"BLIND_ARM_{chr(65 + i)}" for i in range(len(hashed))]
    sealed_map = {
        aliases[i]: {"identity_hash": hashed[i][0], "true_name": hashed[i][1], "role": hashed[i][2]}
        for i in range(len(hashed))
    }
    sealed_payload = {
        "schema": "blind-bakeoff-sealed-key/2",
        "created_at": datetime.now(UTC).isoformat(),
        "salt": salt,
        "mapping": sealed_map,
    }
    sealed_key_path.parent.mkdir(parents=True, exist_ok=True)
    sealed_key_path.write_text(json.dumps(sealed_payload, indent=2) + "\n", encoding="utf-8")
    key_digest = hashlib.sha256(json.dumps(sealed_payload, sort_keys=True).encode()).hexdigest()

    public_arms = [
        {"alias": aliases[i], "identity_hash": hashed[i][0], "verdict": "PENDING_PROSPECTIVE_WINDOW"}
        for i in range(len(hashed))
    ]
    if public_manifest_path is not None:
        public_manifest_path.parent.mkdir(parents=True, exist_ok=True)
        public_manifest_path.write_text(
            json.dumps({
                "schema": "blind-bakeoff-public-manifest/2",
                "created_at": sealed_payload["created_at"],
                "sealed_key_sha256": key_digest,
                "arms": public_arms,
            }, indent=2) + "\n",
            encoding="utf-8",
        )
    return {
        "blinded_arms": public_arms,
        "sealed_key_sha256": key_digest,
        "sealed_key_path": str(sealed_key_path),
    }


def _run_cost_and_attribution_breakeven(
    panel_1d: dict[str, list[BarPoint]],
    daily_targets: dict[datetime, dict[str, float]],
) -> list[dict]:
    """Review Priority #3 & F11: Sweep fees & missed fills across SLOW_100%, SLOW_40%+CASH control."""
    by_start = {s: {b.ts_start: b for b in panel_1d.get(s, [])} for s in BASE_13_SYMBOLS}
    by_avail = {s: {b.ts_avail: b for b in panel_1d.get(s, [])} for s in BASE_13_SYMBOLS}
    dates = sorted(daily_targets)
    rows = []

    for arm_name, scale in (("FIXED_SLOW_S1_S5_100PCT", 1.0), ("SLOW_40PCT_PLUS_CASH_CONTROL", 0.40)):
        for fee_bps in (8.5, 16.0, 25.0, 40.0):
            for miss_step in (0, 4):  # 0 = 0% missed fills; 4 = skip every 4th rebalance (25% missed)
                ledger = SelfFinancingLedger(Decimal("1000"), fee_rate=Decimal(str(fee_bps / 10_000.0)), fee_in_received_asset=True)
                nav: dict[str, float] = {}
                last_px: dict[str, float] = {}
                for idx, ts in enumerate(dates):
                    ef, tr = resolve_bar_prices(BASE_13_SYMBOLS, by_start, by_avail, ts, last_px)
                    ep = {s: Decimal(str(p)) for s, p in ef.items()}
                    if miss_step == 0 or (idx % miss_step != 0):
                        tgt = {s: w * scale for s, w in daily_targets[ts].items()}
                        ledger.rebalance_to_targets(ts, tgt, ep, tradable_symbols=tr)
                    nav[ts.date().isoformat()] = float(ledger.mark_nav(ep))
                m = portfolio_metrics(nav, starting_nav=1000.0)
                rows.append({
                    "arm": arm_name,
                    "fee_bps": fee_bps,
                    "missed_fill_pct": 0 if miss_step == 0 else 25,
                    "ending_nav": m["ending_nav"],
                    "ret_pct": m["ret_pct"],
                    "ann_sharpe": m["ann_sharpe"],
                    "max_dd_pct": m["max_dd_pct"],
                    "fees_usdt": round(float(ledger.total_fees_quote_equiv), 2),
                })
    return rows


def run_venue_clocks_cadence_and_breakeven_study(
    wallex_db: Path,
    multi_venue_db: Path,
    report_path: Path,
    receipt_path: Path,
    sealed_key_path: Path,
) -> dict:
    """Execute Ideas 12, 13, 14 and the Cost/Capacity Break-Even & Slow-40% Attribution Sweep."""
    matched = _load_matched_live_books(wallex_db, multi_venue_db, ("BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT"))
    all_syms = tuple(dict.fromkeys(BASE_13_SYMBOLS + IGNITION_18_CRYPTO))
    con = open_readonly_market_db(wallex_db)
    try:
        panel_1d = {s: load_keyed_candles(con, s, "1d", limit=2500) for s in BASE_13_SYMBOLS}
        panel_1h = {s: load_keyed_candles(con, s, "1h", limit=26000) for s in all_syms}
    finally:
        con.close()

    sigs_13 = compute_slow_sleeves(panel_1d, BASE_13_SYMBOLS)
    eval_dates = [d for d in sorted(sigs_13) if d >= datetime(2022, 6, 1, tzinfo=UTC)]
    daily_breadth = extract_daily_breadth(sigs_13)
    daily_targets = _extract_daily_s1_s5_targets(panel_1d, sigs_13, eval_dates, BASE_13_SYMBOLS, fee_rate=Decimal("0.0016"))
    panel_2h = {s: resample_hourly_to_bucket(panel_1h[s], 2, offset_hours=0) for s in all_syms if panel_1h[s]}

    payload = {
        "generated_at": datetime.now(UTC).isoformat(),
        "executor_state": "DISARMED",
        "idea_12_price_discovery": _run_idea_12_price_discovery(matched),
        "idea_13_event_vs_fixed_cadence": _run_idea_13_event_vs_fixed_cadence(panel_2h, daily_breadth),
        "idea_14_blind_bakeoff": _run_idea_14_blind_bakeoff_manifest(sealed_key_path),
        "cost_and_slow40_breakeven_sweep": _run_cost_and_attribution_breakeven(panel_1d, daily_targets),
    }
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    receipt_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    _write_markdown(report_path, payload)
    return payload


def _write_markdown(report_path: Path, p: dict) -> None:
    lines = [
        "# Post-Repair Cross-Venue Clocks, Cadence, Blind Bake-Off & Cost Break-Even Study (Menu Ideas 12, 13, 14 + Review #3)",
        "",
        f"- **Generated:** `{p['generated_at']}` · **Executor:** `{p['executor_state']}` (`$0` funded budget)",
        "",
        "## Idea 12 — Cross-Venue Price Discovery (With 1-Step Delay & Swapped-Label Controls)",
        "",
        "| Symbol | Samples | WLX→NBX Hit% (bps) | NBX→WLX Hit% (bps) | WLX Delayed +1 Step (bps) | Swapped Placebo (bps) |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for r in p["idea_12_price_discovery"]:
        lines.append(
            f"| `{r['symbol']}` | `{r['samples']}` | `{r['wlx_leads_nbx_hit_pct']:.1f}%` (`{r['wlx_leads_nbx_bps']:+.2f}`) | `{r['nbx_leads_wlx_hit_pct']:.1f}%` (`{r['nbx_leads_wlx_bps']:+.2f}`) | `{r['wlx_delayed_1step_bps']:+.2f}` | `{r['swapped_placebo_bps']:+.2f}` |"
        )
    i13 = p["idea_13_event_vs_fixed_cadence"]
    lines.extend([
        "",
        "## Idea 13 — Event-Driven vs. Fixed-Cadence Engine Runs (Measured CPU & Missed-Trigger Cost)",
        f"- **Evaluations:** `{i13['fixed_2h_evaluations']}` fixed → `{i13['event_triggered_evaluations']}` event (`{i13['cpu_evaluations_saved_pct']:.1f}%` fewer evals)",
        f"- **Measured Process CPU:** `{i13['fixed_cpu_ms']:.1f} ms` → `{i13['event_cpu_ms']:.1f} ms` (**`{i13['measured_cpu_saved_pct']:.1f}%` CPU saved**) · **p95 Bar Latency:** `{i13['fixed_p95_bar_ms']:.4f} ms` vs `{i13['event_p95_bar_ms']:.4f} ms`",
        f"- **Triggers Captured:** `{i13['event_triggers_captured']} / {i13['fixed_triggers']}` (`{i13['trigger_capture_rate_pct']:.2f}%`) · **Missed Trigger 24h Net P&L (bps):** `{i13['missed_triggers_net_24h_bps']}`",
        "",
        "## Idea 14 — Blind Prospective Paper Bake-Off Manifest (Concealed Salt, Key Outside Git)",
        f"- **Sealed Key SHA-256 Commitment:** `{p['idea_14_blind_bakeoff'].get('sealed_key_sha256')}`",
        "",
        "| Blinded Alias | Identity Hash | Status |",
        "| --- | --- | --- |",
    ])
    for b in p["idea_14_blind_bakeoff"]["blinded_arms"]:
        lines.append(f"| `{b['alias']}` | `{b['identity_hash']}` | `{b['verdict']}` |")
    lines.extend([
        "",
        "## Review Priority #3 & F11 — Cost/Missed-Fill Break-Even Sweep & `SLOW_40PCT_PLUS_CASH` Control",
        "",
        "| Arm | Fee (bps) | Missed Fills% | Ending NAV | Return | Ann. Sharpe | MaxDD | Fees ($) |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ])
    for r in p["cost_and_slow40_breakeven_sweep"]:
        lines.append(
            f"| `{r['arm']}` | `{r['fee_bps']:.1f}` | `{r['missed_fill_pct']}%` | `${r['ending_nav']:.2f}` | `{r['ret_pct']:+.2f}%` | `{r['ann_sharpe']:.3f}` | `{r['max_dd_pct']:.2f}%` | `${r['fees_usdt']:.2f}` |"
        )
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
