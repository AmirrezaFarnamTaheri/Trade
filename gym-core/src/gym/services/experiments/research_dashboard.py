"""Offline interactive HTML research dashboard generator with daily-return histograms and 5-panel evidence."""
from __future__ import annotations

import json
import math
from datetime import UTC, datetime
from pathlib import Path
from statistics import median

from ...adapters.candle_reader import load_keyed_candles, open_readonly_market_db
from ...domain.strategy_sleeves import compute_slow_sleeves
from .ensemble_study import (
    COHORT_SYMBOLS,
    _daily_returns_map,
    _run_self_financing_arm,
)


def compute_return_histogram(
    returns: list[float],
    *,
    bin_min_pct: float = -6.0,
    bin_max_pct: float = 6.0,
    bin_step_pct: float = 0.5,
) -> dict:
    """Bin daily decimal returns into fixed percentage buckets with overflow tails and summary stats."""
    n_mid = int(round((bin_max_pct - bin_min_pct) / bin_step_pct))
    labels = [f"<{bin_min_pct:.1f}%"]
    for i in range(n_mid):
        lo = bin_min_pct + i * bin_step_pct
        hi = lo + bin_step_pct
        labels.append(f"{lo:+.1f}% to {hi:+.1f}%")
    labels.append(f">{bin_max_pct:.1f}%")

    counts = [0] * len(labels)
    pcts = [r * 100.0 for r in returns]
    for p in pcts:
        if p < bin_min_pct:
            counts[0] += 1
        elif p >= bin_max_pct:
            counts[-1] += 1
        else:
            idx = int((p - bin_min_pct) / bin_step_pct)
            idx = max(0, min(n_mid - 1, idx))
            counts[idx + 1] += 1

    n = len(pcts)
    if n == 0:
        return {"labels": labels, "counts": counts, "stats": {"n": 0}}
    mean_p = sum(pcts) / n
    var_p = sum((x - mean_p) ** 2 for x in pcts) / max(1, n - 1)
    std_p = math.sqrt(var_p)
    skew = (
        sum(((x - mean_p) / std_p) ** 3 for x in pcts) / n
        if std_p > 1e-12
        else 0.0
    )
    return {
        "labels": labels,
        "counts": counts,
        "stats": {
            "n": n,
            "mean_bps": round(mean_p * 100.0, 2),
            "median_bps": round(median(pcts) * 100.0, 2),
            "std_pct": round(std_p, 3),
            "skew": round(skew, 3),
            "pos_days_pct": round(sum(1 for x in pcts if x > 0) / n * 100.0, 1),
            "flat_days_pct": round(sum(1 for x in pcts if abs(x) < 1e-6) / n * 100.0, 1),
            "worst_day_pct": round(min(pcts), 2),
            "best_day_pct": round(max(pcts), 2),
        },
    }


def _compute_live_histograms(db_path: Path) -> dict:
    con = open_readonly_market_db(db_path)
    try:
        panel_1d = {sym: load_keyed_candles(con, sym, "1d", limit=2500) for sym in COHORT_SYMBOLS}
    finally:
        con.close()
    signals = compute_slow_sleeves(panel_1d, COHORT_SYMBOLS)
    eval_dates = [d for d in sorted(signals) if d >= datetime(2022, 6, 1, tzinfo=UTC)]
    leader = _run_self_financing_arm("DROP_S2", panel_1d, signals, eval_dates)
    buyhold = _run_self_financing_arm("STATIC_GOLD_AND_CRYPTO", panel_1d, signals, eval_dates)
    leader_rets = list(_daily_returns_map(leader["nav_by_date"]).values())
    bh_rets = list(_daily_returns_map(buyhold["nav_by_date"]).values())
    return {
        "leader": compute_return_histogram(leader_rets),
        "buyhold": compute_return_histogram(bh_rets),
    }


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}


def build_dashboard_payload(evidence_dir: Path, db_path: Path | None = None) -> dict:
    """Assemble all 5 research panels from evidence JSON receipts and optional market.db histograms."""
    first = _load_json(evidence_dir / "2026-11-24-first-ensemble-decision-receipt.json")
    deep = _load_json(evidence_dir / "2026-11-24-leader-deep-dive.json")
    fast = _load_json(evidence_dir / "2026-11-24-fast-sleeve-attribution.json")
    venue = _load_json(evidence_dir / "2026-11-24-venue-execution-cost.json")
    exp_abc = _load_json(evidence_dir / "2026-11-24-expansion-and-margin.json")
    gru = _load_json(evidence_dir / "2026-11-24-gru-prototypes.json")
    orth = _load_json(evidence_dir / "2026-11-25-orthogonal-alpha.json")
    smart_exec = _load_json(evidence_dir / "2026-11-25-smart-execution.json")
    fwd_score = _load_json(evidence_dir / "2026-11-25-champion-forward-score.json")
    health = _load_json(evidence_dir / "2026-11-25-operational-health.json")

    histograms = _compute_live_histograms(db_path) if (db_path is not None and db_path.is_file()) else {
        "leader": compute_return_histogram([]),
        "buyhold": compute_return_histogram([]),
    }

    # Panel 2: Unified strategy comparison table combining first receipt + deep-dive leader & hysteresis
    arms_first = first.get("arms", {})
    hyst = deep.get("study_a_s2_hysteresis", {})
    strategy_rows = []
    if "DROP_S2_LEADER" in hyst:
        d = hyst["DROP_S2_LEADER"]
        strategy_rows.append({
            "name": "S1 + S5 Leader (DROP_S2)",
            "status": "LEADER",
            "ending_nav": d["metrics_full"]["ending_nav"],
            "ret_pct": d["metrics_full"]["ret_pct"],
            "ann_sharpe": d["metrics_full"]["ann_sharpe"],
            "max_dd_pct": d["metrics_full"]["max_dd_pct"],
            "stress_ret_pct": d["metrics_stress"]["ret_pct"],
            "fees_usdt": d["total_fees_usdt"],
        })
    for key, label, status in (
        ("FIXED_S1", "S1 Trend Alone", "BASELINE"),
        ("FIXED_ENSEMBLE_S1_S2_S5", "Raw S1 + S2 + S5", "RETIRED"),
        ("ADAPTIVE_VOTE", "Adaptive Vote", "RETIRED"),
        ("LOGISTIC_VETO", "ML Logistic Veto", "RETIRED"),
        ("STATIC_GOLD_AND_CRYPTO", "Buy & Hold (13 Coins)", "BENCHMARK"),
        ("CASH_USDT", "Cash (USDT)", "CONTROL"),
    ):
        if key in arms_first:
            a = arms_first[key]
            strategy_rows.append({
                "name": label,
                "status": status,
                "ending_nav": a["full"]["ending_nav"],
                "ret_pct": a["full"]["ret_pct"],
                "ann_sharpe": a["full"]["ann_sharpe"],
                "max_dd_pct": a["full"]["max_dd_pct"],
                "stress_ret_pct": a["stress_seen"]["ret_pct"],
                "fees_usdt": a["fees_usdt"],
            })
    if "S2_HYSTERESIS_25_55" in hyst:
        h = hyst["S2_HYSTERESIS_25_55"]
        strategy_rows.insert(2, {
            "name": "S1 + S5 + S2 Hysteresis (25/55)",
            "status": "RETIRED",
            "ending_nav": h["metrics_full"]["ending_nav"],
            "ret_pct": h["metrics_full"]["ret_pct"],
            "ann_sharpe": h["metrics_full"]["ann_sharpe"],
            "max_dd_pct": h["metrics_full"]["max_dd_pct"],
            "stress_ret_pct": h["metrics_stress"]["ret_pct"],
            "fees_usdt": h["total_fees_usdt"],
        })

    # Panel 3: Factor attribution & 2x2 entry/exit
    ex2 = deep.get("study_b_entry_exit_2x2", {})
    entry_exit_rows = []
    if "DROP_S2_LEADER" in hyst:
        m = hyst["DROP_S2_LEADER"]["metrics_full"]
        ms = hyst["DROP_S2_LEADER"]["metrics_stress"]
        entry_exit_rows.append({
            "label": "S1+S5 + ADMM Optimizer (Leader)",
            "ret_pct": m["ret_pct"],
            "ann_sharpe": m["ann_sharpe"],
            "max_dd_pct": m["max_dd_pct"],
            "stress_ret_pct": ms["ret_pct"],
        })
    for key, label in (
        ("REAL_ENTRY_SLEEVE_EXIT", "Real Entry + Sleeve Exit (EqWt)"),
        ("REAL_ENTRY_FIXED_20D_EXIT", "Real Entry + 20d Fixed Exit"),
        ("RANDOM_ENTRY_SLEEVE_EXIT_5SEED_AVG", "Random Entry + Sleeve Exit (5-Seed)"),
        ("RANDOM_ENTRY_FIXED_20D_EXIT_5SEED_AVG", "Random Entry + 20d Fixed Exit (5-Seed)"),
    ):
        if key in ex2:
            c = ex2[key]
            mf = c.get("metrics_full", c)
            ms_ret = c["metrics_stress"]["ret_pct"] if "metrics_stress" in c else c.get("stress_ret_pct", 0.0)
            entry_exit_rows.append({
                "label": label,
                "ret_pct": mf["ret_pct"],
                "ann_sharpe": mf["ann_sharpe"],
                "max_dd_pct": mf["max_dd_pct"],
                "stress_ret_pct": ms_ret,
            })

    # Panel 4: Fast sleeves S3/S4 +1h clock-shift
    fast_rows = []
    for key, label in (
        ("s3_wallex_offset_0h", "S3 Panic Reversion (0h UTC)"),
        ("s3_wallex_offset_1h", "S3 Panic Reversion (+1h Shift)"),
        ("s3_nobitex_cf_offset_0h", "S3 Nobitex Counterfactual (0h)"),
        ("s4_wallex_offset_0h", "S4 Vol Breakout (0h UTC)"),
        ("s4_wallex_offset_1h", "S4 Vol Breakout (+1h Shift)"),
        ("s4_nobitex_cf_offset_0h", "S4 Nobitex Counterfactual (0h)"),
    ):
        if key in fast:
            f = fast[key]
            fast_rows.append({
                "label": label,
                "ret_pct": f["ret_pct"],
                "ann_sharpe": f["ann_sharpe"],
                "max_dd_pct": f["max_dd_pct"],
            })

    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "histograms": histograms,
        "strategies": strategy_rows,
        "factor_attribution": deep.get("study_b_factor_attribution", {}),
        "entry_exit_2x2": entry_exit_rows,
        "fast_sleeves": fast_rows,
        "venue_execution": venue.get("symbols", []),
        "causal_execution": deep.get("study_c_causal_execution", []),
        "exp_abc_spot": exp_abc.get("spot_and_overlay_arms", []),
        "exp_abc_margin": exp_abc.get("margin_standalone_arms", []),
        "gru_ignition": gru.get("prototype_2_gru_ignition", {}),
        "orthogonal_alpha": orth,
        "smart_execution": smart_exec.get("rows", []),
        "forward_score": fwd_score,
        "operational_health": health,
    }


def render_dashboard_html(payload: dict) -> str:
    """Render a 100% offline, zero-CDN interactive HTML5 Canvas dashboard."""
    data_json = json.dumps(payload, ensure_ascii=False)
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>TradingGYM — Complete Quantitative Research Dashboard</title>
<style>
  :root {{
    --bg: #0b0f17;
    --panel: #131926;
    --panel-alt: #182032;
    --border: #253047;
    --text: #e6edf7;
    --muted: #8fa1bf;
    --accent: #38bdf8;
    --green: #22c55e;
    --amber: #f59e0b;
    --red: #ef4444;
    --purple: #a78bfa;
  }}
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0;
    font-family: Inter, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    background: var(--bg);
    color: var(--text);
    line-height: 1.45;
  }}
  header {{
    padding: 20px 28px;
    border-bottom: 1px solid var(--border);
    background: linear-gradient(180deg, #101726 0%, #0b0f17 100%);
    display: flex;
    flex-wrap: wrap;
    justify-content: space-between;
    align-items: center;
    gap: 12px;
  }}
  header h1 {{ margin: 0; font-size: 1.35rem; font-weight: 700; letter-spacing: -0.01em; }}
  header .sub {{ color: var(--muted); font-size: 0.85rem; margin-top: 4px; }}
  .badge {{
    display: inline-flex;
    align-items: center;
    gap: 8px;
    padding: 6px 12px;
    border-radius: 999px;
    font-size: 0.78rem;
    font-weight: 600;
    background: rgba(245, 158, 11, 0.14);
    color: var(--amber);
    border: 1px solid rgba(245, 158, 11, 0.4);
  }}
  main {{
    max-width: 1420px;
    margin: 0 auto;
    padding: 22px 24px 48px;
    display: grid;
    gap: 20px;
  }}
  .kpi-row {{
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(190px, 1fr));
    gap: 12px;
  }}
  .kpi {{
    background: var(--panel);
    border: 1px solid var(--border);
    border-radius: 10px;
    padding: 14px 16px;
  }}
  .kpi .lbl {{ color: var(--muted); font-size: 0.76rem; text-transform: uppercase; letter-spacing: 0.05em; }}
  .kpi .val {{ font-size: 1.45rem; font-weight: 700; margin-top: 4px; }}
  .kpi .note {{ color: var(--muted); font-size: 0.78rem; margin-top: 2px; }}
  .pos {{ color: var(--green); }}
  .neg {{ color: var(--red); }}
  .acc {{ color: var(--accent); }}
  .panel {{
    background: var(--panel);
    border: 1px solid var(--border);
    border-radius: 12px;
    padding: 18px 20px;
  }}
  .panel-head {{
    display: flex;
    flex-wrap: wrap;
    justify-content: space-between;
    align-items: center;
    gap: 10px;
    margin-bottom: 12px;
  }}
  .panel h2 {{ margin: 0; font-size: 1.05rem; font-weight: 650; }}
  .panel p.desc {{ margin: 4px 0 0; color: var(--muted); font-size: 0.84rem; }}
  .controls {{ display: flex; flex-wrap: wrap; gap: 6px; }}
  button.tab {{
    background: var(--panel-alt);
    color: var(--muted);
    border: 1px solid var(--border);
    padding: 6px 11px;
    border-radius: 7px;
    font-size: 0.8rem;
    cursor: pointer;
    font-weight: 500;
  }}
  button.tab.active {{
    background: rgba(56, 189, 248, 0.16);
    color: var(--accent);
    border-color: var(--accent);
  }}
  .grid-2 {{
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(460px, 1fr));
    gap: 20px;
  }}
  .canvas-wrap {{ position: relative; width: 100%; height: 320px; }}
  canvas {{ width: 100%; height: 100%; display: block; }}
  .tooltip {{
    position: fixed;
    pointer-events: none;
    background: #0a0f1c;
    border: 1px solid var(--accent);
    color: var(--text);
    padding: 8px 11px;
    border-radius: 8px;
    font-size: 0.79rem;
    box-shadow: 0 8px 24px rgba(0, 0, 0, 0.55);
    opacity: 0;
    transition: opacity 0.08s ease;
    z-index: 999;
    white-space: pre-line;
  }}
  .legend {{
    display: flex;
    flex-wrap: wrap;
    gap: 14px;
    margin-top: 8px;
    font-size: 0.8rem;
    color: var(--muted);
  }}
  .legend span {{ display: inline-flex; align-items: center; gap: 6px; }}
  .swatch {{ width: 11px; height: 11px; border-radius: 3px; display: inline-block; }}
  table {{ width: 100%; border-collapse: collapse; margin-top: 12px; font-size: 0.82rem; }}
  th, td {{ padding: 7px 9px; border-bottom: 1px solid var(--border); text-align: right; }}
  th:first-child, td:first-child {{ text-align: left; }}
  th {{ color: var(--muted); font-weight: 600; font-size: 0.76rem; text-transform: uppercase; }}
  tr.leader-row {{ background: rgba(34, 197, 94, 0.08); }}
</style>
</head>
<body>
<header>
  <div>
    <h1>TradingGYM — Complete Quantitative Research Dashboard</h1>
    <div class="sub">100% Offline Interactive Evidence · 1,638-Day Self-Financing Paper Replay + 5.4h Live Multi-Venue Audit · Generated <span id="gen-ts"></span></div>
  </div>
  <div class="badge">PAPER_ONLY · EXECUTOR DISARMED ($0 FUNDED BUDGET)</div>
</header>

<main>
  <section class="kpi-row" id="kpi-row"></section>

  <!-- Panel 1: Daily Return Distribution Histogram -->
  <section class="panel">
    <div class="panel-head">
      <div>
        <h2>1. Daily Return Distribution Histogram — Standing Leader (S1+S5) vs. Buy &amp; Hold</h2>
        <p class="desc">Exact 1,638-day daily returns binned in 0.5% buckets (overflow tails at &lt;-6% and &gt;+6%). Hover any bar for exact day counts and tail risk.</p>
      </div>
      <div class="controls">
        <button class="tab active" id="btn-both" onclick="setHistMode('both')">Overlay Both</button>
        <button class="tab" id="btn-leader" onclick="setHistMode('leader')">S1+S5 Leader Only</button>
        <button class="tab" id="btn-bh" onclick="setHistMode('buyhold')">Buy &amp; Hold Only</button>
      </div>
    </div>
    <div class="canvas-wrap"><canvas id="c-hist"></canvas></div>
    <div class="legend" id="hist-stats"></div>
  </section>

  <!-- Panel 2: Strategy & Ablation Comparison -->
  <section class="panel">
    <div class="panel-head">
      <div>
        <h2>2. Strategy &amp; Ablation Comparison (1,638 Days, $1,000 Start, 13 bps Fee)</h2>
        <p class="desc">Compare the standing leader against every tested challenger, baseline, and retired sleeve across all 5 key metrics.</p>
      </div>
      <div class="controls" id="strat-tabs">
        <button class="tab active" onclick="setStratMetric('ann_sharpe', this)">Ann. Sharpe</button>
        <button class="tab" onclick="setStratMetric('ending_nav', this)">Ending NAV ($)</button>
        <button class="tab" onclick="setStratMetric('max_dd_pct', this)">Max Drawdown (%)</button>
        <button class="tab" onclick="setStratMetric('stress_ret_pct', this)">Bear Stress (%)</button>
        <button class="tab" onclick="setStratMetric('fees_usdt', this)">Total Fees ($)</button>
      </div>
    </div>
    <div class="canvas-wrap"><canvas id="c-strat"></canvas></div>
  </section>

  <div class="grid-2">
    <!-- Panel 3: Factor Attribution & 2x2 Entry/Exit -->
    <section class="panel">
      <div class="panel-head">
        <div>
          <h2>3. 2×2 Entry vs. Exit Decomposition &amp; ADMM Uplift</h2>
          <p class="desc">Proves both entry and exit add value over random, and ADMM nearly doubles Sharpe (0.64 → 1.01).</p>
        </div>
      </div>
      <div class="canvas-wrap"><canvas id="c-2x2"></canvas></div>
      <table id="t-factor"></table>
    </section>

    <!-- Panel 4: Retired Fast Sleeves -->
    <section class="panel">
      <div class="panel-head">
        <div>
          <h2>4. Retired Fast Sleeves (S3 &amp; S4) — +1h UTC Clock-Shift Fragility</h2>
          <p class="desc">S3 flipped from +9.76% to -2.82% on a 1-hour clock shift; S4 lost across every offset and fee tier.</p>
        </div>
      </div>
      <div class="canvas-wrap"><canvas id="c-fast"></canvas></div>
    </section>
  </div>

  <!-- Panel 5: Live Multi-Venue Execution Cost & Causal BUY/SELL -->
  <div class="grid-2">
    <section class="panel">
      <div class="panel-head">
        <div>
          <h2>5A. Live Execution Cost: Wallex L1 vs. Nobitex (-30%)</h2>
          <p class="desc">5.40h matched live quotes (301–307 pairs/symbol). All-in one-way taker cost = ½ spread + fee.</p>
        </div>
      </div>
      <div class="canvas-wrap"><canvas id="c-venue"></canvas></div>
    </section>

    <section class="panel">
      <div class="panel-head">
        <div>
          <h2>5B. Causal Execution BUY vs. SELL Asymmetry (Wallex)</h2>
          <p class="desc">Zero-lookahead p35 opportunistic passive savings (bps) vs immediate taker with displayed size limits.</p>
        </div>
      </div>
      <div class="canvas-wrap"><canvas id="c-causal"></canvas></div>
    </section>
  </div>

  <!-- Panel 6: Experiments A, B, and C -->
  <section class="panel">
    <div class="panel-head">
      <div>
        <h2>6. Experiments A, B, and C — 33-Market Expansion, ML Tilt &amp; Paper Margin</h2>
        <p class="desc">Expanding to 33 assets diluted Sharpe (1.011 → 0.748); Wallex 32.85%/yr borrow crushed slow leverage &amp; L1 pairs (-88.1%). Note: once the same-day ts_avail causality leak was fixed, all intraday 2h/3h/6h crash breakers whipsawed below BASE_13_S1_S5.</p>
      </div>
    </div>
    <div class="canvas-wrap"><canvas id="c-abc"></canvas></div>
    <table id="t-margin"></table>
  </section>

  <!-- Panel 7: 2h GRU-Ignition & Orthogonal Alpha Audit (3A/3B/3C) -->
  <div class="grid-2">
    <section class="panel">
      <div class="panel-head">
        <div>
          <h2>7A. 2h Rare Momentum Ignition + GRU-Ignition Sequence Sizer</h2>
          <p class="desc">Purged walk-forward 3-seed GRU (AUC 0.558, +12.5pp win-rate spread) dynamically gating 0.5×/1.0×/1.5× leverage with 0 liquidations and ~$11 3-year borrow.</p>
        </div>
      </div>
      <div class="canvas-wrap"><canvas id="c-gru"></canvas></div>
    </section>

    <section class="panel">
      <div class="panel-head">
        <div>
          <h2>7B. Orthogonal Alpha Audit (3A Flush/Dead-Cat, 3B Cov-Only GRU-Vol, 3C PAXG/Macro)</h2>
          <p class="desc">All 3A/3B challengers decisively retired; XAUTUSDT beat PAXGUSDT (1.011 vs 0.865); standalone Macro Commodities (+24.4%, corr +0.082) parked for future multi-year history.</p>
        </div>
      </div>
      <div class="canvas-wrap"><canvas id="c-orth"></canvas></div>
    </section>
  </div>

  <!-- Panel 8: Side-Asymmetric Smart Execution & Live Forward Champion Tracker -->
  <section class="panel">
    <div class="panel-head">
      <div>
        <h2>8. Side-Asymmetric Smart Execution Audit ($250 Walked L2 Depth) &amp; Live Forward Champion Status</h2>
        <p class="desc">Nobitex (-30%) passive BUY + immediate smart-taker SELL cuts execution drag by +8.1 to +21.9 bps/leg across 4/4 live pairs. Below: live untouched forward tracker for frozen v1 Champion (70% BASE_13_S1_S5 + 30% GRU-Ignition).</p>
      </div>
    </div>
    <div class="canvas-wrap"><canvas id="c-smart"></canvas></div>
    <table id="t-fwd"></table>
  </section>
</main>

<div class="tooltip" id="tip"></div>

<script>
const DATA = {data_json};
document.getElementById('gen-ts').textContent = DATA.generated_at.slice(0, 19).replace('T', ' ') + ' UTC';

const tip = document.getElementById('tip');
function showTip(ev, text) {{
  tip.textContent = text;
  tip.style.opacity = '1';
  tip.style.left = Math.min(window.innerWidth - 280, ev.clientX + 14) + 'px';
  tip.style.top = Math.max(12, ev.clientY - 12) + 'px';
}}
function hideTip() {{ tip.style.opacity = '0'; }}

function setupCanvas(id) {{
  const c = document.getElementById(id);
  const dpr = window.devicePixelRatio || 1;
  const rect = c.getBoundingClientRect();
  c.width = Math.max(300, Math.floor(rect.width * dpr));
  c.height = Math.max(200, Math.floor(rect.height * dpr));
  const ctx = c.getContext('2d');
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  return {{ c, ctx, w: rect.width, h: rect.height }};
}}

function bindHover(canvas, rects) {{
  canvas.onmousemove = (ev) => {{
    const r = canvas.getBoundingClientRect();
    const x = ev.clientX - r.left, y = ev.clientY - r.top;
    const hit = rects.find(b => x >= b.x && x <= b.x + b.w && y >= b.y && y <= b.y + b.h);
    if (hit) showTip(ev, hit.tip); else hideTip();
  }};
  canvas.onmouseleave = hideTip;
}}

// KPI Cards
(function renderKpis() {{
  const leader = DATA.strategies.find(s => s.status === 'LEADER') || {{}};
  const fa = (DATA.factor_attribution || {{}}).DROP_S2_LEADER || {{}};
  const vAvg = DATA.venue_execution.length
    ? (DATA.venue_execution.reduce((a, b) => a + b.oneway_taker_saving_bps, 0) / DATA.venue_execution.length).toFixed(1)
    : '0.0';
  const cards = [
    {{ lbl: 'Standing Leader (S1+S5)', val: '$' + (leader.ending_nav || 0).toFixed(2), cls: 'pos', note: '+' + (leader.ret_pct || 0) + '% vs +100.2% B&H' }},
    {{ lbl: 'Annualized Sharpe', val: (leader.ann_sharpe || 0).toFixed(3), cls: 'acc', note: 'MaxDD ' + (leader.max_dd_pct || 0) + '% (vs 58.2% B&H)' }},
    {{ lbl: 'Bear-Year Stress (Seen)', val: (leader.stress_ret_pct || 0).toFixed(2) + '%', cls: 'pos', note: 'vs -36.44% Buy & Hold' }},
    {{ lbl: 'Orthogonal Alpha (OLS)', val: '+' + (fa.ann_alpha_pct || 0).toFixed(2) + '%/yr', cls: 'pos', note: 'Residual Sharpe ' + (fa.residual_ann_sharpe || 0) + ' · R² ' + (fa.r_squared || 0) }},
    {{ lbl: 'Nobitex Execution Edge', val: '+' + vAvg + ' bps/leg', cls: 'acc', note: '5/5 live pairs cheaper (~1.1%/yr)' }},
  ];
  document.getElementById('kpi-row').innerHTML = cards.map(k =>
    `<div class="kpi"><div class="lbl">${{k.lbl}}</div><div class="val ${{k.cls}}">${{k.val}}</div><div class="note">${{k.note}}</div></div>`
  ).join('');
}})();

// Panel 1: Histogram
let histMode = 'both';
function setHistMode(mode) {{
  histMode = mode;
  ['both', 'leader', 'bh'].forEach(m => document.getElementById('btn-' + m).classList.remove('active'));
  document.getElementById('btn-' + (mode === 'buyhold' ? 'bh' : mode)).classList.add('active');
  drawHistogram();
}}

function drawHistogram() {{
  const {{ c, ctx, w, h }} = setupCanvas('c-hist');
  const L = DATA.histograms.leader, B = DATA.histograms.buyhold;
  const labels = L.labels || [];
  const pad = {{ l: 48, r: 16, t: 18, b: 56 }};
  const pw = w - pad.l - pad.r, ph = h - pad.t - pad.b;
  const maxC = Math.max(1, ...(histMode === 'leader' ? L.counts : histMode === 'buyhold' ? B.counts : [...L.counts, ...B.counts]));

  ctx.clearRect(0, 0, w, h);
  ctx.strokeStyle = '#253047'; ctx.fillStyle = '#8fa1bf'; ctx.font = '11px Inter, sans-serif';
  for (let i = 0; i <= 4; i++) {{
    const y = pad.t + ph * (1 - i / 4);
    ctx.beginPath(); ctx.moveTo(pad.l, y); ctx.lineTo(w - pad.r, y); ctx.stroke();
    ctx.fillText(Math.round(maxC * i / 4), 6, y + 4);
  }}

  const step = pw / Math.max(1, labels.length);
  const rects = [];
  labels.forEach((lbl, i) => {{
    const x0 = pad.l + i * step + 1;
    const bw = Math.max(2, step - 2);
    if (histMode === 'both' || histMode === 'buyhold') {{
      const bh = (B.counts[i] / maxC) * ph;
      ctx.fillStyle = 'rgba(245, 158, 11, 0.42)';
      ctx.fillRect(x0, pad.t + ph - bh, bw, bh);
    }}
    if (histMode === 'both' || histMode === 'leader') {{
      const lh = (L.counts[i] / maxC) * ph;
      ctx.fillStyle = 'rgba(56, 189, 248, 0.72)';
      ctx.fillRect(x0 + bw * 0.14, pad.t + ph - lh, bw * 0.72, lh);
    }}
    rects.push({{
      x: x0, y: pad.t, w: bw, h: ph,
      tip: `Bucket: ${{lbl}}\nS1+S5 Leader: ${{L.counts[i]}} days\nBuy & Hold: ${{B.counts[i]}} days`
    }});
    if (i % 3 === 0 || i === labels.length - 1) {{
      ctx.save();
      ctx.translate(x0 + bw / 2, pad.t + ph + 10);
      ctx.rotate(-0.45);
      ctx.fillStyle = '#8fa1bf';
      ctx.textAlign = 'right';
      ctx.fillText(lbl.split(' to ')[0], 0, 0);
      ctx.restore();
    }}
  }});
  bindHover(c, rects);

  const ls = L.stats || {{}}, bs = B.stats || {{}};
  document.getElementById('hist-stats').innerHTML = `
    <span><i class="swatch" style="background:#38bdf8"></i><b>S1+S5 Leader:</b> std ${{ls.std_pct}}% · skew ${{ls.skew}} · worst ${{ls.worst_day_pct}}% · best +${{ls.best_day_pct}}% · flat-cash ${{ls.flat_days_pct}}% days</span>
    <span><i class="swatch" style="background:#f59e0b"></i><b>Buy &amp; Hold:</b> std ${{bs.std_pct}}% · skew ${{bs.skew}} · worst ${{bs.worst_day_pct}}% · best +${{bs.best_day_pct}}%</span>
  `;
}}

// Generic Horizontal/Vertical Bar Helper
function drawBarChart(canvasId, items, opts) {{
  const {{ c, ctx, w, h }} = setupCanvas(canvasId);
  const pad = {{ l: opts.leftPad || 52, r: 18, t: 20, b: opts.bottomPad || 64 }};
  const pw = w - pad.l - pad.r, ph = h - pad.t - pad.b;
  const vals = items.map(it => it.val);
  const minV = Math.min(0, ...vals), maxV = Math.max(0.0001, ...vals);
  const span = (maxV - minV) || 1;
  const zeroY = pad.t + (maxV / span) * ph;

  ctx.clearRect(0, 0, w, h);
  ctx.strokeStyle = '#253047'; ctx.fillStyle = '#8fa1bf'; ctx.font = '11px Inter, sans-serif';
  for (let i = 0; i <= 4; i++) {{
    const v = minV + (span * i / 4);
    const y = pad.t + ((maxV - v) / span) * ph;
    ctx.beginPath(); ctx.moveTo(pad.l, y); ctx.lineTo(w - pad.r, y); ctx.stroke();
    ctx.fillText(opts.fmt ? opts.fmt(v) : v.toFixed(1), 6, y + 4);
  }}
  ctx.strokeStyle = '#475569';
  ctx.beginPath(); ctx.moveTo(pad.l, zeroY); ctx.lineTo(w - pad.r, zeroY); ctx.stroke();

  const step = pw / Math.max(1, items.length);
  const bw = Math.min(54, step * 0.62);
  const rects = [];
  items.forEach((it, i) => {{
    const cx = pad.l + i * step + step / 2;
    const yVal = pad.t + ((maxV - it.val) / span) * ph;
    const top = Math.min(zeroY, yVal);
    const bh = Math.max(2, Math.abs(zeroY - yVal));
    ctx.fillStyle = it.color;
    ctx.fillRect(cx - bw / 2, top, bw, bh);
    ctx.fillStyle = '#e6edf7';
    ctx.textAlign = 'center';
    ctx.fillText(opts.fmt ? opts.fmt(it.val) : it.val.toFixed(2), cx, it.val >= 0 ? top - 5 : top + bh + 12);
    ctx.fillStyle = '#8fa1bf';
    ctx.save();
    ctx.translate(cx, pad.t + ph + 12);
    ctx.rotate(-0.28);
    ctx.textAlign = 'right';
    ctx.fillText(it.label, 4, 0);
    ctx.restore();
    rects.push({{ x: cx - bw / 2, y: top, w: bw, h: bh, tip: it.tip }});
  }});
  bindHover(c, rects);
}}

function drawGroupedBars(canvasId, groups, s1Name, s2Name, c1, c2, fmt) {{
  const {{ c, ctx, w, h }} = setupCanvas(canvasId);
  const pad = {{ l: 50, r: 16, t: 22, b: 52 }};
  const pw = w - pad.l - pad.r, ph = h - pad.t - pad.b;
  const allV = groups.flatMap(g => [g.v1, g.v2]);
  const minV = Math.min(0, ...allV), maxV = Math.max(0.0001, ...allV);
  const span = (maxV - minV) || 1;
  const zeroY = pad.t + (maxV / span) * ph;

  ctx.clearRect(0, 0, w, h);
  ctx.strokeStyle = '#253047'; ctx.fillStyle = '#8fa1bf'; ctx.font = '11px Inter, sans-serif';
  for (let i = 0; i <= 4; i++) {{
    const v = minV + (span * i / 4);
    const y = pad.t + ((maxV - v) / span) * ph;
    ctx.beginPath(); ctx.moveTo(pad.l, y); ctx.lineTo(w - pad.r, y); ctx.stroke();
    ctx.fillText(fmt(v), 6, y + 4);
  }}
  ctx.strokeStyle = '#475569';
  ctx.beginPath(); ctx.moveTo(pad.l, zeroY); ctx.lineTo(w - pad.r, zeroY); ctx.stroke();

  const step = pw / Math.max(1, groups.length);
  const bw = Math.min(24, step * 0.32);
  const rects = [];
  groups.forEach((g, i) => {{
    const cx = pad.l + i * step + step / 2;
    [{{ v: g.v1, col: c1, dx: -bw - 2, nm: s1Name }}, {{ v: g.v2, col: c2, dx: 2, nm: s2Name }}].forEach(b => {{
      const yv = pad.t + ((maxV - b.v) / span) * ph;
      const top = Math.min(zeroY, yv);
      const bh = Math.max(2, Math.abs(zeroY - yv));
      ctx.fillStyle = b.col;
      ctx.fillRect(cx + b.dx, top, bw, bh);
      rects.push({{ x: cx + b.dx, y: top, w: bw, h: bh, tip: `${{g.label}} · ${{b.nm}}: ${{fmt(b.v)}}\n${{g.extra || ''}}` }});
    }});
    ctx.fillStyle = '#8fa1bf'; ctx.textAlign = 'center';
    ctx.fillText(g.label, cx, pad.t + ph + 18);
  }});
  // Mini legend top-right
  ctx.fillStyle = c1; ctx.fillRect(w - 190, 4, 10, 10);
  ctx.fillStyle = '#e6edf7'; ctx.textAlign = 'left'; ctx.fillText(s1Name, w - 176, 13);
  ctx.fillStyle = c2; ctx.fillRect(w - 95, 4, 10, 10);
  ctx.fillStyle = '#e6edf7'; ctx.fillText(s2Name, w - 81, 13);
  bindHover(c, rects);
}}

// Panel 2: Strategy Comparison
let stratMetric = 'ann_sharpe';
function setStratMetric(metric, btn) {{
  stratMetric = metric;
  document.querySelectorAll('#strat-tabs button').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');
  drawStrategies();
}}

function drawStrategies() {{
  const fmts = {{
    ann_sharpe: v => v.toFixed(2),
    ending_nav: v => '$' + Math.round(v),
    max_dd_pct: v => v.toFixed(1) + '%',
    stress_ret_pct: v => (v >= 0 ? '+' : '') + v.toFixed(1) + '%',
    fees_usdt: v => '$' + Math.round(v),
  }};
  const items = DATA.strategies.map(s => ({{
    label: s.name,
    val: s[stratMetric],
    color: s.status === 'LEADER' ? '#22c55e' : s.status === 'BENCHMARK' ? '#f59e0b' : s.status === 'BASELINE' ? '#38bdf8' : '#64748b',
    tip: `${{s.name}} [${{s.status}}]\nNAV: $${{s.ending_nav}} (${{s.ret_pct >= 0 ? '+' : ''}}${{s.ret_pct}}%)\nSharpe: ${{s.ann_sharpe}} · MaxDD: ${{s.max_dd_pct}}%\nBear Stress: ${{s.stress_ret_pct}}% · Fees: $${{s.fees_usdt}}`,
  }}));
  drawBarChart('c-strat', items, {{ fmt: fmts[stratMetric], bottomPad: 76 }});
}}

// Panel 3: 2x2 Entry/Exit + OLS Factor Table
function draw2x2AndFactor() {{
  const items = DATA.entry_exit_2x2.map((c, idx) => ({{
    label: c.label.replace(' (5-Seed)', ''),
    val: c.ann_sharpe,
    color: idx === 0 ? '#22c55e' : idx < 3 ? '#38bdf8' : '#64748b',
    tip: `${{c.label}}\nAnn. Sharpe: ${{c.ann_sharpe}}\nFull Return: +${{c.ret_pct}}%\nMaxDD: ${{c.max_dd_pct}}% · Bear Stress: ${{c.stress_ret_pct}}%`,
  }}));
  drawBarChart('c-2x2', items, {{ fmt: v => v.toFixed(2), bottomPad: 74 }});

  const fa = DATA.factor_attribution || {{}};
  const rows = Object.entries(fa).map(([k, v]) => `
    <tr class="${{k === 'DROP_S2_LEADER' ? 'leader-row' : ''}}">
      <td>${{k}}</td>
      <td class="pos">+${{v.ann_alpha_pct.toFixed(2)}}%</td>
      <td>${{v.beta_btc.toFixed(3)}}</td>
      <td>${{v.beta_gold.toFixed(3)}}</td>
      <td>${{v.r_squared.toFixed(3)}}</td>
      <td class="acc">${{v.residual_ann_sharpe.toFixed(3)}}</td>
    </tr>
  `).join('');
  document.getElementById('t-factor').innerHTML = `
    <thead><tr><th>Arm (OLS, N=839)</th><th>Ann. Alpha</th><th>β BTC</th><th>β Gold</th><th>R²</th><th>Resid. Sharpe</th></tr></thead>
    <tbody>${{rows}}</tbody>
  `;
}}

// Panel 4: Fast Sleeves S3/S4
function drawFastSleeves() {{
  const items = DATA.fast_sleeves.map(f => ({{
    label: f.label,
    val: f.ret_pct,
    color: f.ret_pct >= 0 ? '#f59e0b' : '#ef4444',
    tip: `${{f.label}}\nReturn: ${{f.ret_pct >= 0 ? '+' : ''}}${{f.ret_pct}}%\nAnn. Sharpe: ${{f.ann_sharpe}}\nMaxDD: ${{f.max_dd_pct}}%`,
  }}));
  drawBarChart('c-fast', items, {{ fmt: v => (v >= 0 ? '+' : '') + v.toFixed(1) + '%', bottomPad: 76 }});
}}

// Panel 5A: Venue Execution
function drawVenue() {{
  const groups = DATA.venue_execution.map(r => ({{
    label: r.symbol,
    v1: r.wallex_allin_taker_bps,
    v2: r.nobitex_allin_taker_bps,
    extra: `One-way saving: +${{r.oneway_taker_saving_bps}} bps · Annual S1+S5 saving: +${{r.est_annual_s1_s5_drag_saving_pct}}%/yr`,
  }}));
  drawGroupedBars('c-venue', groups, 'Wallex L1', 'Nobitex -30%', '#ef4444', '#22c55e', v => v.toFixed(1) + 'bp');
}}

// Panel 5B: Causal BUY vs SELL
function drawCausal() {{
  const bySym = {{}};
  DATA.causal_execution.forEach(r => {{
    bySym[r.symbol] = bySym[r.symbol] || {{ label: r.symbol, v1: 0, v2: 0 }};
    if (r.side === 'BUY') bySym[r.symbol].v1 = r.opportunistic_savings_bps;
    else bySym[r.symbol].v2 = r.opportunistic_savings_bps;
  }});
  drawGroupedBars('c-causal', Object.values(bySym), 'BUY Savings', 'SELL Savings', '#22c55e', '#ef4444', v => (v >= 0 ? '+' : '') + v.toFixed(1));
}}

// Panel 6: Experiments A, B, C
function drawExpAbc() {{
  const items = (DATA.exp_abc_spot || []).map(a => ({{
    label: a.name.replace('EXP_', '').replace('_ASSETS', '').replace('_LEADER', ''),
    val: a.full.ann_sharpe,
    color: a.name.includes('4H_CRASH_EXIT') ? '#22c55e' : a.name.includes('BASE_13') ? '#38bdf8' : a.name.includes('33_') ? '#f59e0b' : '#a78bfa',
    tip: `${{a.name}}\nNAV: $${{a.full.ending_nav}} (${{a.full.ret_pct >= 0 ? '+' : ''}}${{a.full.ret_pct}}%)\nSharpe: ${{a.full.ann_sharpe}} · MaxDD: ${{a.full.max_dd_pct}}%\nBear Stress: ${{a.stress.ret_pct}}% · Fees: $${{a.fees_usdt}} · Borrow: $${{a.extra_borrow_usdt}}`,
  }}));
  if (items.length) drawBarChart('c-abc', items, {{ fmt: v => v.toFixed(2), bottomPad: 84 }});

  const mRows = (DATA.exp_abc_margin || []).map(m => `
    <tr>
      <td>${{m.name}}</td>
      <td class="${{m.ret_pct >= 0 ? 'pos' : 'neg'}}">$${{m.ending_nav.toFixed(2)}} (${{m.ret_pct >= 0 ? '+' : ''}}${{m.ret_pct}}%)</td>
      <td>${{m.ann_sharpe.toFixed(3)}}</td>
      <td>${{m.max_dd_pct.toFixed(2)}}%</td>
      <td>${{m.trades}}</td>
      <td class="${{m.liquidations > 0 ? 'neg' : 'pos'}}">${{m.liquidations}}</td>
      <td>$${{m.total_borrow_usdt.toFixed(2)}}</td>
      <td>$${{m.total_fees_usdt.toFixed(2)}}</td>
    </tr>
  `).join('');
  if (mRows) {{
    document.getElementById('t-margin').innerHTML = `
      <thead><tr><th>Standalone Paper Margin (Wallex 32.85%/yr Borrow)</th><th>Ending NAV</th><th>Sharpe</th><th>MaxDD</th><th>Trades</th><th>Liquidations</th><th>Borrow ($)</th><th>Fees+Slip ($)</th></tr></thead>
      <tbody>${{mRows}}</tbody>
    `;
  }}
}}

// Panel 7A: GRU-Ignition
function drawGruIgnition() {{
  const g = DATA.gru_ignition || {{}};
  const arms = [
    ['Plain 1.0x (NBX16)', g.plain_1x_nbx16, '#38bdf8'],
    ['Plain 1.5x (NBX16)', g.plain_15x_nbx16, '#f59e0b'],
    ['GRU Dynamic (NBX16)', g.gru_dynamic_nbx16, '#22c55e'],
    ['GRU Dynamic (WLX25)', g.gru_dynamic_wlx25, '#a78bfa'],
  ].filter(x => x[1]).map(([label, a, color]) => ({{
    label,
    val: a.ann_sharpe,
    color,
    tip: `${{label}}\nNAV: $${{a.ending_nav}} (${{a.ret_pct >= 0 ? '+' : ''}}${{a.ret_pct}}%)\nBear Stress: ${{a.stress_ret_pct >= 0 ? '+' : ''}}${{a.stress_ret_pct}}%\nSharpe: ${{a.ann_sharpe}} · MaxDD: ${{a.max_dd_pct}}%\nLiqs: ${{a.liquidations}} · Borrow: $${{a.total_borrow_usdt}}`,
  }}));
  if (arms.length) drawBarChart('c-gru', arms, {{ fmt: v => v.toFixed(2), bottomPad: 72 }});
}}

// Panel 7B: Orthogonal Alpha Audit (3A/3B/3C)
function drawOrthogonal() {{
  const o = DATA.orthogonal_alpha || {{}};
  const b3 = o.study_3b_gru_vol_cov_only || {{}};
  const c3 = o.study_3c_gold_and_macro || {{}};
  const fl = (o.study_3a_flush_rebound || [])[0];
  const dc = (o.study_3a_deadcat_short || [])[0];
  const items = [];
  if (b3.baseline_13) items.push({{ label: 'BASE_13 XAUT', val: b3.baseline_13.full.ann_sharpe, color: '#22c55e', tip: `BASE_13 XAUT (Champion)\nSharpe: ${{b3.baseline_13.full.ann_sharpe}} · Return: +${{b3.baseline_13.full.ret_pct}}%` }});
  if (c3.paxg_base_13) items.push({{ label: 'BASE_13 PAXG', val: c3.paxg_base_13.full.ann_sharpe, color: '#38bdf8', tip: `BASE_13 PAXG\nSharpe: ${{c3.paxg_base_13.full.ann_sharpe}} · Return: +${{c3.paxg_base_13.full.ret_pct}}%` }});
  if (b3.gru_vol_cov_only) items.push({{ label: 'GRU-Vol Cov', val: b3.gru_vol_cov_only.full.ann_sharpe, color: '#f59e0b', tip: `GRU-Vol Cov Only\nSharpe: ${{b3.gru_vol_cov_only.full.ann_sharpe}} · Return: +${{b3.gru_vol_cov_only.full.ret_pct}}%` }});
  if (c3.macro_standalone) items.push({{ label: 'Macro RP', val: c3.macro_standalone.ann_sharpe, color: '#a78bfa', tip: `Macro Commodities RP\nSharpe: ${{c3.macro_standalone.ann_sharpe}} · Return: +${{c3.macro_standalone.ret_pct}}% · Corr: ${{c3.macro_standalone.corr_vs_base_13}}` }});
  if (fl) items.push({{ label: 'Flush Long 0h', val: fl.ann_sharpe, color: '#ef4444', tip: `Flush Rebound 2h 0h\nSharpe: ${{fl.ann_sharpe}} · Return: ${{fl.ret_pct}}%` }});
  if (dc) items.push({{ label: 'DeadCat Short', val: dc.ann_sharpe, color: '#ef4444', tip: `DeadCat Short 2h 0h\nSharpe: ${{dc.ann_sharpe}} · Return: ${{dc.ret_pct}}%` }});
  if (items.length) drawBarChart('c-orth', items, {{ fmt: v => v.toFixed(2), bottomPad: 72 }});
}}

// Panel 8: Side-Asymmetric Smart Execution & Live Forward Champion Tracker
function drawSmartAndForward() {{
  const groups = [];
  (DATA.smart_execution || []).forEach(r => {{
    groups.push({{ label: r.symbol.replace('USDT', '') + ' BUY', v1: r.buy.wallex_taker_bps, v2: r.buy.asym_router_bps, extra: `Saving: +${{r.buy.saving_asym_vs_wallex_bps}} bps · Passive Fill: ${{r.buy.passive_buy_fill_pct}}%` }});
    groups.push({{ label: r.symbol.replace('USDT', '') + ' SELL', v1: r.sell.wallex_taker_bps, v2: r.sell.asym_router_bps, extra: `Saving: +${{r.sell.saving_asym_vs_wallex_bps}} bps · Nobitex Cheaper: ${{r.sell.nobitex_cheaper_pct}}%` }});
  }});
  if (groups.length) drawGroupedBars('c-smart', groups, 'Wallex Taker', 'Asym Router', '#ef4444', '#22c55e', v => v.toFixed(1) + 'bp');

  const f = DATA.forward_score || {{}};
  const h = DATA.operational_health || {{}};
  document.getElementById('t-fwd').innerHTML = `
    <thead><tr><th>Live Champion Forward Tracker</th><th>Status</th><th>Forward Days</th><th>Paper NAV</th><th>e-Process</th><th>Cash Weight</th><th>Live NBX / WLX Spread</th><th>Watchdog Health</th></tr></thead>
    <tbody><tr class="leader-row">
      <td>70% BASE_13_S1_S5 (XAUT) + 30% Frozen GRU-Ignition</td>
      <td class="pos">${{f.status || 'PENDING'}}</td>
      <td>${{f.forward_days || 0}} (${{f.observations || 0}} snaps)</td>
      <td>$${{(f.paper_nav || 1000).toFixed(2)}} (${{(f.cum_ret_pct || 0) >= 0 ? '+' : ''}}${{(f.cum_ret_pct || 0).toFixed(2)}}%)</td>
      <td>${{(f.e_process || 1).toFixed(4)}}</td>
      <td>${{((f.latest_cash_weight ?? 1) * 100).toFixed(1)}}%</td>
      <td>${{f.median_live_nobitex_spread_bps ?? '—'}} / ${{f.median_live_wallex_spread_bps ?? '—'}} bps</td>
      <td class="${{h.overall_status === 'OK' ? 'pos' : 'acc'}}">${{h.overall_status || '—'}} (DISARMED)</td>
    </tr></tbody>
  `;
}}

function drawAll() {{
  drawHistogram();
  drawStrategies();
  draw2x2AndFactor();
  drawFastSleeves();
  drawVenue();
  drawCausal();
  drawExpAbc();
  drawGruIgnition();
  drawOrthogonal();
  drawSmartAndForward();
}}
window.addEventListener('resize', drawAll);
drawAll();
</script>
</body>
</html>
"""


def generate_research_dashboard(
    evidence_dir: Path,
    output_html: Path,
    *,
    db_path: Path | None = None,
) -> dict:
    """Build payload from evidence receipts + market.db histograms and write self-contained offline HTML."""
    payload = build_dashboard_payload(evidence_dir, db_path=db_path)
    html = render_dashboard_html(payload)
    output_html.parent.mkdir(parents=True, exist_ok=True)
    output_html.write_text(html, encoding="utf-8")
    return {
        "output_html": str(output_html),
        "bytes": len(html.encode("utf-8")),
        "leader_hist_days": payload["histograms"]["leader"]["stats"].get("n", 0),
        "strategies_count": len(payload["strategies"]),
        "venue_symbols": len(payload["venue_execution"]),
    }
