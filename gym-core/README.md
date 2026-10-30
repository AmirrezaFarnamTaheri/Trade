# gym-core — Workstream A1 (Observatory)

Public Wallex collector, venue-rule service and a bilingual (EN/FA) Markets screen with a pair-scoped
"When can I act?" bar. There is no order code. Nothing here can place, cancel or sign anything.

```powershell
cd gym-core
uv sync
uv run gymctl run              # live public data -> ..\data\live, UI on http://127.0.0.1:8765/
uv run gymctl run --demo       # synthetic DEMO feed -> data\demo (never mixed with live)
uv run gymctl rules list       # also: add|edit|import|export|disable|rollback|preset|check
uv run gymctl demo-seed         # 72 h synthetic DEMO history (USDTTMN goes silent in its closures)
uv run gymctl paper BTCTMN --demo   # A2: EMA replay + baselines + gross-to-net waterfall -> data\demo\runs\<id>.json
uv run pytest -q               # A1 + A2 checks
```

`paper` takes `--from/--to` (zoned ISO), `--res 1min|15min|1h|1day`, `--fast/--slow`, `--fee`, `--latency-ms` and
`--rules point-in-time|today`. The same inputs give the same `run_id` and `outputs` digest. Fills use the first qualified
ask (buy) or bid (sell) at or after decision + latency. Rule closures, quota and minimums cause nonfills. Holdings are
never auto-sold at the end. Results are in USDT-equivalent through a disclosed USDTTMN mid valuation rate.

Layout: `gym.domain` is pure (types, quality flags, rule evaluation), `gym.adapters` handles Wallex REST/WS, SQLite and
Zstd segments, `gym.services` holds the collector and rule service, and `gym.api` is the loopback aiohttp server with the
single-file UI. The domain must not import I/O; a test enforces this.

Storage: raw WS/REST frames go to hourly `raw/YYYYMMDD/*.jsonl.zst` with a SHA-256 manifest in `segments`. `market.db` holds
change-only `book_top`, `trades`, `quality_events` and the immutable `regime_events` rule ledger.

The first run preloads the preset `usdt-irt-october-2026`: USDTTMN closed 21:00-09:00 Tehran from 30 Sep, then 23:30-11:30
from 18 Oct, plus a 2,000 USDT purchase cap per Tehran day. Status is REPORTED, from an announcement. Edit it in
Settings -> Venue rules.

Not yet (A3): paper-session lifecycle (WARMING_UP..ENDED), Journal UI, diagnostics (lookahead/parity), evidence report.
Deferred: session/volume bars, venue-candle cross-check, limit orders.
