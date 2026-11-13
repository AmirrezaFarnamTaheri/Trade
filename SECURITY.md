# Security

TradingGYM is a single-operator research tool. Funded execution is DISARMED, but the repository still holds
custody code (the Rust executor vault) and an exchange API-key store.

## Reporting

Report a vulnerability privately through GitHub's "Report a vulnerability" (Security tab) on this repository.
Do not open a public issue for anything that exposes keys, the executor's pipes or the loopback API token.

## Scope

In scope: the executor service and its pipes, the credential vault and ledger, the gym-core loopback API and its
token boundary, installer and update scripts, and CI supply chain.

Out of scope: paper-research results, and anything that requires an administrator on the host.

## Boundaries worth knowing

- The loopback API trusts the Host header for loopback and a per-run token for writes and private reads; the
  public reads are listed in `gym-core/src/gym/api/__init__.py`.
- Public-read decision (finding S-8, recorded 2026-11-10). Without the token, a loopback caller may read market
  quotes, health and readiness, capabilities, the strategy catalogue, the list of saved runs and a saved run's full
  record (`/api/runs/{id}`, including its economic-evidence report), rules and rule checks, and the chaos report.
  These hold paper results and public venue data only, never keys, account data or journals. A run's summary views,
  the timeline, backups, account observations, order events, venue facts and every write need the token.
  `tests/test_api_contract.py` enumerates every route and fails if one becomes public without being listed.
- Secrets at rest use Windows DPAPI. User-scope DPAPI trusts every process running as that user.
- Executor updates are verified against a SHA-256 manifest. Once an administrator pins an update key
  (`update-signing.pub` in the executor code folder), the manifest must also carry a valid ECDSA P-256 signature,
  checked natively by the elevated update script; helpers are re-checked against the kept manifest before launch.
