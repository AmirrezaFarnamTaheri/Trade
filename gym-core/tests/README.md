# Verification

From `gym-core`, run `uv sync` and use the maintained check entry point. During collection, --no-sync avoids replacing
the running Windows launcher; sync dependency changes with the collector stopped:

```powershell
uv run --no-sync python scripts/check.py lint
uv run --no-sync python scripts/check.py test
uv run --no-sync python scripts/check.py ui
uv run --no-sync python scripts/check.py smoke
uv run --no-sync python scripts/check.py all
```

`test` runs the complete Python suite, including real disposable-worker and
Node DOM contracts when their prerequisites exist. `ui` selects the page, asset,
syntax and DOM contracts. `smoke` runs the separate real-browser test and needs
an installed supported browser. Do not report a DOM check as visual or installed
Windows qualification. Node and browser prerequisites are distinct.

For a focused regression, `uv run --no-sync python -m pytest tests/test_name.py -q` uses
the same test runner. Synthetic fixtures stay in temporary test stores and
cannot become live market, account or performance evidence.
