# gym-core — Workstream A1 (Observatory)

Public Wallex collector, venue-rule service and a bilingual (EN/FA) Markets screen with a pair-scoped
"When can I act?" bar. There is no order code. Nothing here can place, cancel or sign anything.

```powershell
cd gym-core
uv sync
uv run gymctl run              # live public data -> ..\data\live, UI on http://127.0.0.1:8765/
uv run gymctl run --demo       # synthetic DEMO feed -> data\demo (never mixed with live)
uv run gymctl rules list       # also: add|edit|import|export|disable|rollback|preset|check
uv run pytest -q               # A1 checks
```

Layout: `gym.domain` is pure (types, quality flags, rule evaluation), `gym.adapters` handles Wallex REST/WS, SQLite and
Zstd segments, `gym.services` holds the collector and rule service, and `gym.api` is the loopback aiohttp server with the
single-file UI. The domain must not import I/O; a test enforces this.

Storage: raw WS/REST frames go to hourly `raw/YYYYMMDD/*.jsonl.zst` with a SHA-256 manifest in `segments`. `market.db` holds
change-only `book_top`, `trades`, `quality_events` and the immutable `regime_events` rule ledger.

The first run preloads the preset `usdt-irt-october-2026`: USDTTMN closed 21:00-09:00 Tehran from 30 Sep, then 23:30-11:30
from 18 Oct, plus a 2,000 USDT purchase cap per Tehran day. Status is REPORTED, from an announcement. Edit it in
Settings -> Venue rules.

Not in A1 (comes in A2/A3): consolidator/bars, Data Portal, strategy, simulator, CashBook, paper sessions, Journal.
