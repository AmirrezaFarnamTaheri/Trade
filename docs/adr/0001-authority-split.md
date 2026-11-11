# ADR 0001: Three runtimes, one kind of authority each

Status: Accepted (records the existing design)

## Context

TradingGYM observes a venue, runs paper research, calls advisory AI providers and may one day hold money. Each
of those carries a different risk: public data is harmless, provider keys cost money, venue credentials move it.

## Decision

- **gym-core (Python)** owns public observation, exact storage and paper research. It holds no venue order
  transport. Its loopback API trusts the Host header for loopback and a per-run token for writes.
- **model-gateway (Node)** owns provider credentials and advisory completions. Its output is research-only and
  never reaches an order path.
- **executor (Rust, Windows service)** owns custody, the hash-chained ledger and every money-path policy. It runs
  as a restricted service account behind protected named pipes; it starts DISARMED.
- The browser UI combines none of these powers; it calls each through its own boundary.

## Consequences

- A compromise of research code or the gateway cannot place an order.
- Money semantics live in Rust while the simulator lives in Python, so research and execution can disagree; the
  shared conformance fixtures in `contracts/` are the guard until a shared kernel exists (A-1).
