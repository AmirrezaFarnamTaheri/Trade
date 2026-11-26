# Live Venue Certification & Pre-Capital Gate Checklist (F-01 / F-02)

> **Current Posture:** `TradingGYMExecutor` is **`DISARMED / NOT CERTIFIED`** (`$0` funded budget).
> No live venue order transport, autonomous arming, or leveraged/short execution is permitted until every gate below is evidenced and signed off.

---

## Mandatory Pre-Live Certification Gates

| Gate | Requirement | Pass Criterion | Status |
| :--- | :--- | :--- | :--- |
| **G1 — Read-Only Reconciliation Soak** | Run read-only live exchange balance & order-list reconciliation against Nobitex/Wallex for **7–14 consecutive days**. | `0` unexplained ledger drift events; `0` 10× IRR/TMN denomination mismatches (`assert_irr_tmn_denomination_sane`). | `PENDING` |
| **G2 — Deterministic Custody DST (`REL-01`)** | Pass seeded fault-injection simulation (`custody_deterministic_sim.rs`) across crash, duplicate-ack, partial-fill, and stale-evidence scenarios. | `100%` hold conservation; fail-closed `Unknown` lock preservation. | `PASS` |
| **G3 — Spot-Only Admission (`ADR 0009`)** | Enforce `enforce_spot_only_strategy(...)` on all active strategies; reject `leverage != 1.0` or `short_allowed = True`. | `0` leveraged or short intents admitted without Rust `MarginAccount` + `LiabilityLedger` + `LiquidationWatchdog`. | `PASS` |
| **G4 — Micro-Cap Canary Pilot** | Bounded `$10–$50` funded canary under hard daily-loss ceiling, order-rate cap, and verified withdrawal-path deny-list (`enforce_venue_path_policy`). | Verified live kill-switch drill (`STOP` -> zero working orders within SLA). | `GATED` |
| **G5 — Off-Host Disaster Recovery (`F-06`)** | Automated encrypted ledger backup (`EncryptedBackupManifest` + B3 encrypt/decrypt verification) to independent off-host storage. | Independent restore drill verifies hash-chain tip and active holds. | `SPEC_READY` |
| **G6 — Explicit Operator Sign-Off** | Dual written review of security audit, DSR/FX-attribution report, and canary logs before raising funded budget above `$0`. | Signed operator review artifact committed to `evidence/`. | `GATED` |
