# Security

TradingGYM is a single-operator research tool. Funded execution is DISARMED, but the repository still holds
custody code (the Rust executor vault), provider credentials (the model gateway) and an exchange API-key store.

## Reporting

Report a vulnerability privately through GitHub's "Report a vulnerability" (Security tab) on this repository.
Do not open a public issue for anything that exposes keys, the executor's pipes or the loopback API token.

## Scope

In scope: the executor service and its pipes, the credential vault and ledger, the gym-core loopback API and its
token boundary, the gateway's credential storage, installer and update scripts, and CI supply chain.

Out of scope: paper-research results, and anything that requires an administrator on the host.

## Boundaries worth knowing

- The loopback API trusts the Host header for loopback and a per-run token for writes and private reads; the
  public reads are listed in `gym-core/src/gym/api/__init__.py`.
- Secrets at rest use Windows DPAPI. User-scope DPAPI trusts every process running as that user.
- Executor updates are verified against an operator-supplied SHA-256 manifest; they are not yet signed.
