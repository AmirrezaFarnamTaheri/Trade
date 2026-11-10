# Onboarding: build, verify and change TradingGYM from the docs alone

This page is the checklist a second maintainer follows unaided (findings G-1 and G-5). Each step names the
command and what a pass looks like. Nothing here arms the executor or starts the collector.

## 1. Tools

| Tool | Version | Used by |
|---|---|---|
| Rust | 1.96.0 (pinned in CI) | `executor/` workspace |
| uv | 0.11 or later | `gym-core/` (Python 3.11+, locked in `uv.lock`) |
| Node | 22 | `model-gateway/` |
| Edge or Chrome | current | browser smoke test |
| PowerShell | 5.1 or 7 | `tasks.ps1`, installers in `scripts/windows/` |

## 2. Build and check everything

```powershell
cd gym-core; uv sync --locked --group dev; cd ..
.\tasks.ps1                 # rust, python, node: the same commands as CI
.\tasks.ps1 browser         # real-browser smoke with axe, synthetic data
.\tasks.ps1 sbom            # CycloneDX SBOMs for the three ecosystems into .pi\sbom
.\tasks.ps1 kernel          # optional: the simulator on the Rust money kernel (ADR 0005)
```

A pass ends with `All requested tasks passed.` CI (`.github/workflows/validate.yml`) runs the same steps plus the
Windows VM service smoke, the cross-OS backup drills, the weekly mutation job and the SBOM job.

## 3. Verify a workspace

```powershell
cd gym-core
uv run gymctl --data ..\data doctor            # one pass/fail over stores, segments, journals, disk, backups, keys
uv run gymctl --data ..\data verify-segments   # re-hash every closed raw segment
uv run gymctl --data ..\data timeline          # newest operator activity across the journals
uv run gymctl --data ..\data arm-preflight     # READY/BLOCKED checklist; never arms
```

## 4. Read before changing anything

1. `PRODUCT.md`: what the product is and is not (paper-only, executor DISARMED).
2. `docs/adr/`: the authority split, fail-closed money path, reservation model, startup replay, shared kernel and
   arming decisions.
3. `gym-core/docs/architecture.md` and `executor/README.md`, including its list of test-only, unwired paths.
4. `SECURITY.md`: reporting, the loopback trust model and the public-read set.

## 5. Make a change

- Work on a branch. Every fix gets a regression test that fails without the fix.
- Money arithmetic is `Decimal` in Python and exact integers or `kernel::Exact` in Rust; never floats.
- Wire formats live in `contracts/`. Changing one means updating the golden fixture and every consumer (Python
  and Rust tests load the same file).
- No new function above complexity 20; the ratchet (`gym-core/scripts/complexity_ratchet.py`) fails CI if a
  listed hotspot grows. Lower its baseline when you split one.
- Executor changes that touch admission, custody, reservation or arming need the pre-funding independent review
  before they are wired (ADR 0006).
- Add a line to `CHANGELOG.md`.

## 6. Market store schema changes

`market.db` migrates forward only. `gym.adapters.store.MIGRATIONS` is an ordered list of SQL scripts; on open, every
script past `PRAGMA user_version` runs in one transaction that also bumps the version (five so far). To change the
schema, append a new script, never edit an old one, and add a test that opens a database at the previous version
and checks the migrated result. There is no down-migration: restore from a backup (`gymctl restore-research`) to go
back.

## 7. Releases

Versions follow semantic versioning in `CHANGELOG.md`. An executor bundle ships with `bundle.sha256` and a manifest
signed by the off-host release key (`gymctl release-sign`); `Update-ReadOnlyExecutor.ps1 -Signature` refuses an
unsigned or mismatched manifest. Attach the three SBOMs from the CI `sbom` artifact to a release. Acceptance
evidence goes into `evidence/` as sanitised derivatives listed in `evidence/INDEX.json`.
