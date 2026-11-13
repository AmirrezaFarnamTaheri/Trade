# Historical execution-choice research (improvement plan item 25)

**Status:** paper-only implementation. This does **not** complete Workstream C
controlled integration, grant funded authority, or establish an executable
venue route. The T1/T2, authenticated observation, real manual lifecycle,
venue protection, service-principal isolation, settlement, and operator consent
gates remain open in [the controlled integration runbook](controlled-integration-runbook.md).

## One matched historical comparison

The offline Research Workbench exposes `execution-choice-preview` alongside
`twap-preview`. The caller supplies the **same** fields as TWAP, with
`slices` from 2 through 100. For example, use a completed observation window:

```json
{
  "symbol": "BTCUSDT",
  "from": "2026-10-29T09:00:00Z",
  "to": "2026-10-29T09:30:00Z",
  "side": "BUY",
  "quantity": "0.01",
  "slices": 3,
  "participation": "0.5",
  "fee_rate": "0.001",
  "available_quote": "1000",
  "available_base": "0",
  "max_delay_seconds": 30
}
```

An optional `cost_models` object can contain exactly the explicit dated
`impact_models` and `hourly_costs` described in [market models](market-models.md). Every profile must
have been trained *before* the replay start. No observed fee or cost is assumed
known unless its dated evidence is eligible.

The action uses **one read-only database snapshot** and two calculations:

1. An immediate **one-slice best-quote paper attempt**.
2. The requested N-slice TWAP paper attempt, with identical starting
   balances, participation, fee and modeled impact/spread assumptions.

Both are bounded to recorded quotes available after their respective
scheduled child times. No quote is reused across children of one path.
The result includes both original detailed receipts and explicit fill
quantities. It is supervised by the same 120-second disposable research
worker as other heavy research actions.

### Comparison rules

- If either path fails to fill its **entire** requested quantity, status is
  `NOT_COMPARABLE`, reason `UNMATCHED_FILLED_QUANTITY`. No price
  advantage or winner is invented from unequal executions.
- If both fully fill, status is `FULL_FILL_HISTORICAL`. For BUY, effective
  price is total modeled quote spent divided by **net received base**
  (including fees paid in base). For SELL it is **net received quote**
  divided by base sold (including fees paid in quote).
- `twap_advantage_bps` is positive only when the historical sliced path
  has a lower modeled effective BUY price or higher net effective SELL price;
  negative means the immediate path was cheaper; zero is a tie.
- `retrospective_lower_cost` reports `TWAP`, `IMMEDIATE`, `TIE`, or
  `null`, and is never an actionable future recommendation.

The cost comparison is **not available at the first slot**: by definition
future market observations are used for the retrospective TWAP replay.
Do not use this as a forecast or select a live strategy from it. Top-of-book
quotes and estimated fees are not verified matching-engine fills, and the
replay cannot establish queue priority, venue reservations, settlement or
reliable future capacity.

Every receipt has `funded_authority=false`,
`autonomous_execution=false`, `order_submitted=false`,
`cancel_submitted=false` and `decision_available_at_start=false`.
The browser only selects the read-only local research action; it never
connects to a trade credential or protected executor.

## Verification

```sh
cd gym-core
uvx ruff==0.17.4 check src tests
uv run pytest -q tests/test_execution_choice.py tests/test_premium_twap_prospective.py
uv run --with coverage==7.6.10 coverage run --source=src/gym -m pytest -q
```

Also require the repository's Windows/Linux/Rust/security/browser workflows.
Missing independent host and venue acceptance gates stay visible and block
any assertion that C is production-ready.
