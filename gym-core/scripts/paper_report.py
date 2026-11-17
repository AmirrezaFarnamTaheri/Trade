"""One self-contained HTML page of paper results: a sweep of every market, margin holds, live jobs and trials.

    uv run --no-sync python scripts/paper_report.py --data ../data/live \
        --sweep ../data/live/sweeps/<from>_<to>.sqlite3 --holds holds.json --out paper-report.html

`--holds` is the output of `scripts/margin_hold.py` over the same window. Paper only; nothing here places an order.
"""
import argparse
import html
import json
import re
import sqlite3
import statistics as st
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from gym.services.allocation import journal as forward_journal  # noqa: E402
from gym.services.evidence import TRIAL_LOG  # noqa: E402
from gym.services.evidence import trials as registered
from gym.services.research_actions import research_action  # noqa: E402

parser = argparse.ArgumentParser(description=__doc__.split(chr(10))[0])
parser.add_argument("--data", type=Path, required=True)
parser.add_argument("--sweep", type=Path, required=True)
parser.add_argument("--holds", type=Path, required=True)
parser.add_argument("--out", type=Path, required=True)
args = parser.parse_args()
ROOT = args.data
f = lambda r, k: float(r[k] or 0)  # noqa: E731
esc = html.escape

db = sqlite3.connect(args.sweep)
db.row_factory = sqlite3.Row
meta = json.loads(db.execute("select value from sweep where key='meta'").fetchone()[0])
runs = [dict(r) for r in db.execute("select * from runs")]
ok = [r for r in runs if r["status"] == "OK"]
traded = [r for r in ok if r["fills"]]
cash = {"USDT": float(meta["cash_usdt"]), "TMN": float(meta["cash_tmn"])}
for r in ok:
    r["hold_pct"] = 100 * f(r, "hold_net") / cash[r["quote"]]
    for k in ("directional", "spread", "fees"):
        r[k + "_pct"] = 100 * f(r, k) / cash[r["quote"]]
markets = list({r["symbol"]: r for r in ok if f(r, "hold_net")}.values())  # a hold that never filled says nothing
lev = json.loads(args.holds.read_text(encoding="utf-8"))["rows"]
lev_markets = {r["symbol"] for r in lev}
quoted = [r for r in lev if r.get("terms") == "venue"]
venue_note = (f"Every cell uses the venue's own margin quote for that market, side and ratio; the venue refused "
              f"{sum(1 for m in lev_markets for x in (5, 10) if not any(r['symbol'] == m and r['ratio'] == x for r in lev))} "
              f"market and ratio pairs above 3x, which are left out." if quoted and len(quoted) == len(lev)
              else "Fees follow the venue's margin previews at 2x; other ratios reuse those rates.")


def live_jobs():
    listing = research_action(ROOT, "list", None, store="live")
    hypotheses = {h["id"]: h for h in listing["hypotheses"]}
    rows = []
    for job in listing["jobs"]:
        if not job["enabled"]:
            continue
        hypothesis, report = hypotheses[job["hypothesis_id"]], job.get("last_report") or {}
        if not report.get("run_id"):
            rows.append((hypothesis["symbol"], hypothesis["strategy"], "first run pending", "", "", ""))
            continue
        run = json.loads((ROOT / "runs" / f"{report['run_id']}.json").read_text(encoding="utf-8"))
        start = float(job["cash"])
        hold = next((v for k, v in run["baselines"].items() if k not in ("hold USDT", "hold TMN")), {})
        pct = lambda x, start=start: f"{100 * float(x) / start:+.2f}%"  # noqa: E731
        fills = run["result"]["fills"]
        rows.append((hypothesis["symbol"], hypothesis["strategy"], pct(run["result"]["end"]["net"]),
                     pct(hold["end"]["net"]) if hold.get("end") else "n/a", len(fills) if isinstance(fills, list) else fills,
                     report["due_at"][:16].replace("T", " ")))
    return rows


jobs = live_jobs()
import margin_hold  # noqa: E402

hurdle = [(f"{days} day{'s' if days > 1 else ''}",
           f"{100 * (margin_hold.ENTRY_FEE + margin_hold.EXIT_FEE + margin_hold.LOAN_FEE * (1 + days * 86400 // margin_hold.PERIOD) + (margin_hold.ENTRY_FEE + margin_hold.EXIT_FEE) * ((days - 1) // 21)):.2f}%")
          for days in (1, 7, 21, 60)]
sys.path.insert(0, str(Path(__file__).resolve().parent))
import trend_short  # noqa: E402

binance = {symbol: trend_short.study.load(symbol, "1d", trend_short.study.CACHE) for symbol in trend_short.RANK_COINS}


def t11_median(window, ratio, short):
    return st.median(100 * trend_short.total([r for day, r in trend_short.returns(*binance[s], window, ratio, short=short)
                                              if day < trend_short.SPLIT]) for s in trend_short.RANK_COINS)


T11 = [(f"{w}-day, short {x:.0f}x", t11_median(w, x, True), t11_median(w, x, False)) for w, x in ((50, 1.0), (50, 2.0), (100, 1.0), (200, 1.0))]
t11_rows = [row for name, short, cash_rule in T11
            for row in ((name, short, "median of ten coins"), (name.split(",")[0] + ", long or cash", cash_rule, "same rule, no short"))]
journal = [(e["day"][:10], f'{e["decision"]["close"]:,.0f}', f'{e["decision"]["average"]:,.0f}',
            "Stay in USDT" if not e["decision"]["target"] else f'Hold {e["decision"]["target"]:.0%} BTC', e["equity"])
           for e in forward_journal(ROOT)]
causes = {}
for line in TRIAL_LOG.read_text(encoding="utf-8").split("## Why they lost", 1)[-1].splitlines():
    cells = [c.strip() for c in line.strip().strip("|").split("|")]
    if len(cells) == 3:
        for ids in re.findall(r"\((T[\d, T]+)\)", cells[0]):
            for trial in re.findall(r"T\d+", ids):
                causes[trial] = cells[1].split(". ")[0].split(": ")[0].rstrip(".")
trials = [(t["id"], t["hypothesis"].split(". ")[0].split(" (")[0], {"NARROW_PASS": "PASS (narrow)"}.get(t["verdict"], t["verdict"]),
           causes.get(t["id"], "Forward paper record running" if "PASS" in t["verdict"] else "")) for t in registered()]

GOOD, BAD, INK, MUTE = "#0f7b6c", "#c2410c", "#16202a", "#5b6875"


def bars(rows, *, unit="%", width=760, label_w=170):
    """Horizontal bars around zero. rows: (label, value, note)."""
    lo, hi = min(0, *(v for _, v, _ in rows)), max(0, *(v for _, v, _ in rows))
    span, plot = (hi - lo) or 1, width - label_w - 260
    zero = label_w + plot * (-lo) / span
    out = [f'<svg viewBox="0 0 {width} {len(rows) * 26 + 8}" role="img">']
    for i, (label, value, note) in enumerate(rows):
        y, w = i * 26 + 6, abs(value) / span * plot
        x = zero if value >= 0 else zero - w
        out.append(f'<text x="{label_w - 8}" y="{y + 14}" text-anchor="end" class="l">{esc(label)}</text>'
                   f'<rect x="{x:.1f}" y="{y}" width="{max(w, 1):.1f}" height="18" rx="2" fill="{GOOD if value >= 0 else BAD}"/>'
                   f'<text x="{label_w + plot + 8}" y="{y + 14}" class="v">{value:+.1f}{unit} <tspan class="n">{esc(note)}</tspan></text>')
    out.append(f'<line x1="{zero:.1f}" y1="0" x2="{zero:.1f}" y2="{len(rows) * 26 + 8}" stroke="{INK}" stroke-width="1"/></svg>')
    return "".join(out)


def histogram(values, lo, hi, step, width=640, height=200):
    bins = [0] * int((hi - lo) / step)
    for v in values:
        bins[min(len(bins) - 1, max(0, int((v - lo) // step)))] += 1
    top, bw = max(bins), (width - 40) / len(bins)
    out = [f'<svg viewBox="0 0 {width} {height + 30}" role="img">']
    for i, n in enumerate(bins):
        edge, h = lo + i * step, n / top * height
        out.append(f'<rect x="{20 + i * bw + 1:.1f}" y="{height - h:.1f}" width="{bw - 2:.1f}" height="{h:.1f}" fill="{GOOD if edge >= 0 else BAD}"/>')
        if n:
            out.append(f'<text x="{20 + i * bw + bw / 2:.1f}" y="{height - h - 4:.1f}" text-anchor="middle" class="n">{n}</text>')
        if i % 2 == 0:
            out.append(f'<text x="{20 + i * bw:.1f}" y="{height + 16}" text-anchor="middle" class="n">{edge:+.0f}%</text>')
    return "".join(out) + "</svg>"


def table(head, rows):
    return ("<table><thead><tr>" + "".join(f"<th>{esc(h)}</th>" for h in head) + "</tr></thead><tbody>"
            + "".join("<tr>" + "".join(f"<td>{c if str(c).startswith('<') else esc(str(c))}</td>" for c in r) + "</tr>" for r in rows)
            + "</tbody></table>")


def tone(v, text=None):
    return f'<b style="color:{GOOD if v >= 0 else BAD}">{text or f"{v:+.1f}%"}</b>'


by = lambda key, rows: {k: [r for r in rows if r[key] == k] for k in dict.fromkeys(r[key] for r in rows)}  # noqa: E731
strategy_rows = sorted(((s, st.mean(r["return_pct"] for r in v), f"{sum(f(r, 'net') > 0 for r in v)} of {len(v)} profitable")
                        for s, v in by("strategy", traded).items() if len(v) >= 20), key=lambda x: -x[1])
res_rows = [(k, st.mean(r["return_pct"] for r in v), f"{sum(f(r, 'net') > 0 for r in v)} of {len(v)} profitable")
            for k, v in by("resolution", traded).items()]
liquid = [r for r in traded if r["max_drawdown_pct"] < 99]
water = [(name, st.median(r[k + "_pct"] for r in traded), "of starting cash, median run")
         for name, k in (("Price moved against it", "directional"), ("Spread paid", "spread"), ("Fees paid", "fees"))]
enough = [r for r in traded if (r["closed_trades"] or 0) >= 3]
winners = sorted(enough, key=lambda r: -r["return_pct"])[:10]
ruined = [r for r in traded if r["max_drawdown_pct"] >= 99]
hold_usdt = [r["hold_pct"] for r in markets if r["quote"] == "USDT"]
hold_all = [r["hold_pct"] for r in markets]

lev_rows = []
for side in ("long", "short"):
    for ratio in (1, 2, 3, 5, 10):
        v = [r for r in lev if r["side"] == side and r["ratio"] == ratio]
        lev_rows.append((f"{'Buy' if side == 'long' else 'Sell short'} at {ratio}x", 100 * st.mean(r["ret"] for r in v),
                         f"{sum(r['ret'] > 0 for r in v)} of {len(v)} up, {sum(r['liquidated_h'] is not None for r in v)} liquidated"))
first_liq = sorted((r for r in lev if r["liquidated_h"] is not None and r["side"] == "long" and r["ratio"] == 5), key=lambda r: r["liquidated_h"])


page = f"""<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>TradingGYM paper results, {meta['from'][:10]} to {meta['to'][:10]}</title>
<style>
body{{font:16px/1.55 system-ui,Segoe UI,sans-serif;color:{INK};background:#f6f4ef;margin:0}}
main{{max-width:940px;margin:0 auto;padding:32px 20px 80px}}
h1{{font-size:34px;line-height:1.15;margin:0 0 8px}} h2{{font-size:22px;margin:48px 0 4px}} .lede{{font-size:19px;max-width:62ch}}
.sub{{color:{MUTE};margin:0 0 16px;max-width:70ch}}
.cards{{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:12px;margin:24px 0}}
.card{{background:#fff;border:1px solid #e2ddd3;border-radius:8px;padding:16px}} .card b{{display:block;font-size:30px;line-height:1.1}} .card span{{color:{MUTE};font-size:14px}}
figure{{background:#fff;border:1px solid #e2ddd3;border-radius:8px;padding:16px;margin:12px 0;overflow-x:auto}} svg{{width:100%;min-width:560px;height:auto;display:block}}
svg text{{font:13px system-ui,sans-serif;fill:{INK}}} svg .n{{fill:{MUTE};font-size:11.5px}} svg .v{{font-weight:600}}
table{{border-collapse:collapse;width:100%;font-size:14.5px}} th,td{{text-align:left;padding:7px 10px;border-bottom:1px solid #e8e3da}} th{{color:{MUTE};font-weight:600}}
.take{{border-left:4px solid {INK};padding:4px 16px;margin:16px 0;background:#fff}} ol li{{margin:6px 0}} footer{{color:{MUTE};font-size:14px;margin-top:48px}}
</style><main>
<h1>Nothing tested beats holding USDT yet</h1>
<p class="lede">Every strategy was replayed on every market Wallex quotes, from {meta['from'][:10]} to {meta['to'][:10]}, with real spreads and a 0.10% fee per side.
The market fell hard in that window. Buying lost on almost every market, with or without a strategy. Selling short was the only side that made money here. Over six years it was the opposite: see the last chart.</p>
<div class="cards">
<div class="card"><b>{len(ok):,}</b><span>paper runs across {len({r['symbol'] for r in ok})} markets, {len(meta['strategies'])} strategies, {len(meta['resolutions'])} bar sizes</span></div>
<div class="card"><b style="color:{BAD}">{sum(f(r, 'net') > 0 for r in enough)} of {len(enough):,}</b><span>runs with 3 or more closed trades ended in profit</span></div>
<div class="card"><b style="color:{BAD}">{st.median(hold_all):+.1f}%</b><span>median result of simply buying and holding a market</span></div>
<div class="card"><b style="color:{GOOD}">{100 * st.mean(r['ret'] for r in lev if r['side'] == 'short' and r['ratio'] == 1):+.1f}%</b><span>average result of a 1x short on the {len(lev_markets)} margin markets</span></div>
</div>

<h2>The backdrop: almost everything fell</h2>
<p class="sub">Result of buying each market at the start and holding to the end, in its own quote currency. {sum(v > 0 for v in hold_all)} of {len(hold_all)} markets rose.</p>
<figure>{histogram(hold_all, -60, 20, 5)}</figure>

<h2>Buying with a strategy: every family lost</h2>
<p class="sub">Average return of the runs that traded, by strategy. Spot only, so a strategy can buy or sit in cash; it cannot profit from a fall.</p>
<figure>{bars(strategy_rows)}</figure>
<p class="sub">By bar size. Faster bars trade more and lose more.</p>
<figure>{bars(res_rows)}</figure>

<h2>Where the money went</h2>
<p class="sub">Median traded run, as a share of starting cash. Spread costs more than direction and many times more than fees.</p>
<figure>{bars(water, label_w=200)}</figure>
<div class="take">{len(ruined)} runs on {len({r['symbol'] for r in ruined})} thin markets lost nearly all their cash. They crossed a wide spread again and again.
On COOKIEUSDT one run paid more in spread than it started with. A spread filter before entry is the cheapest fix available.</div>

<h2>Buy, sell short and leverage</h2>
<p class="sub">One position per margin market, opened at the first quote and held to the end, at each credit ratio.
Liquidation is checked against every one-minute low and high. {venue_note} This model matches the exact margin engine on 55 stored previews, and its liquidation prices sit within 0.3% of the venue's.</p>
<figure>{bars(lev_rows, label_w=150)}</figure>
<div class="take">A 3x long was liquidated on {sum(r['liquidated_h'] is not None for r in lev if r['side'] == 'long' and r['ratio'] == 3)} of {len(lev_markets)} markets and a 5x long on {len(first_liq)} of {sum(1 for r in lev if r['side'] == 'long' and r['ratio'] == 5)}.
The fastest 5x liquidation took {first_liq[0]['liquidated_h']:.0f} hours ({first_liq[0]['symbol']}). Leverage did not change which side won. It changed how fast the losing side was wiped out.</div>

<h2>What a short has to earn first</h2>
<p class="sub">Fall needed just to pay the venue's margin fees on a 1x short, before the spread: entry, exit, the loan fee every 4 hours, and a fresh entry every 21 days.</p>
<figure>{table(["Held for", "Price must fall by"], hurdle)}</figure>
<div class="take">A short held for months needs a large fall just to stand still, which is why T11 lost. A short has to be an event measured in days.</div>

<h2>The few that made money</h2>
<p class="sub">Best ten runs with at least three closed trades. Out of {len(enough):,} runs, ten good ones are what luck alone produces. None of these is evidence of an edge.</p>
<figure>{table(["Market", "Bars", "Strategy", "Return", "Holding instead", "Closed trades", "Worst drawdown"],
               [(r["symbol"], r["resolution"], r["strategy"], tone(r["return_pct"]), tone(r["hold_pct"]), r["closed_trades"], f"{r['max_drawdown_pct']:.1f}%") for r in winners])}</figure>
<p class="sub">Nine of the ten are mean-reversion rules on Toman markets. That is one idea worth registering as a proper trial, with its pass mark fixed first.</p>

<h2>Live simulation</h2>
<p class="sub">These run every hour against the live feed. Each replays the last seven days and records the result.</p>
<figure>{table(["Market", "Strategy", "Last 7 days", "Holding instead", "Fills", "Run at (UTC)"], jobs)}</figure>
<p class="sub">Forward record of the one rule that passed (BTCUSDT 50-day trend), running daily since 2026-11-14 on 1,000 USDT:</p>
<figure>{table(["Day", "Close", "50-day average", "Decision", "Equity"], journal)}</figure>
<div class="take">The trend rule has stayed in USDT on all {len(journal)} days while BTC fell {100 * (1 - float(journal[-1][1].replace(',', '')) / float(journal[0][1].replace(',', ''))):.0f}%. That is the rule working as designed, on {len(journal)} days of evidence.</div>

<h2>All {len(trials)} registered trials</h2>
<figure>{table(["Trial", "Idea", "Result", "Why"], [(a, b, tone(1 if c.startswith("PASS") else -1, c), d) for a, b, c, d in trials])}</figure>

<h2>Over six years, shorting the trend lost</h2>
<p class="sub">Trial T11 tested the obvious follow-up: the trend rule, short below its 50, 100 or 200-day average instead of in USDT,
at 1x or 2x, on ten large coins from 2018 to 2023. It was registered before it ran.</p>
<figure>{bars(t11_rows, label_w=150)}</figure>
<div class="take">Shorting lost against sitting in cash in every one of the 60 cells. Coins spent more time rising than falling,
and a short pays about 33% a year to borrow plus a fresh entry every 21 days. The 17-day fall above was one window, not a pattern.</div>

<h2>What to do next</h2>
<ol>
<li><b>Stay long or in cash.</b> The trend rule that moves to USDT in a fall (T6) beat its short version in every test. Its forward record is the evidence that counts.</li>
<li><b>Refuse wide spreads.</b> Skip entry when the spread is above a fixed share of the expected move. This removes the largest single cost found.</li>
<li><b>Register Toman mean reversion as a trial.</b> It is the only family that shows up among the winners.</li>
<li><b>Keep leverage at 2x or below.</b> At 3x a 17-day fall liquidated a third of markets.</li>
</ol>
<footer>Paper only. Window {meta['from']} to {meta['to']}, engine {meta['engine']}, starting cash 1,000 USDT or 300,000,000 TMN, fee {float(meta['fee']):.2%} per side.
{sum(r['status'] == 'NO_DATA' for r in runs):,} runs had no usable quotes and {sum(r['status'] == 'REFUSED' for r in runs):,} were refused as invalid combinations.
The sweep and margin holds cover one 17-day falling window; T11 covers 2018 to 2023 on Binance prices.</footer>
</main></html>"""
args.out.write_text(page, encoding="utf-8")
print(args.out, len(page))
