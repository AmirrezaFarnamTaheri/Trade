# Evidence index

`INDEX.json` holds a SHA-256 for every acceptance receipt, benchmark and study output that the docs cite under
`.pi/`. The receipts themselves stay out of the repository because they can hold host details. Anyone given the
receipts can check them with `uv run --no-sync python scripts/evidence_index.py --verify` (from `gym-core/`);
`tests/test_dd_quick_wins.py` fails when a doc cites a path that has no digest here.
