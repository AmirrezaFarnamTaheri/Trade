# `implied-toman-rate` ranking receipt - 2026-11-16 Tehran

Registered rule and pass marks: `gym-core/docs/trial-log.md`, registration commit `1544a61`;
script commit `35a76be`. Run once with `scripts/implied_rate.py --db ../data/live/market.db`.
The command's output follows. Percentages below are sums of trade returns, not compounded account returns.

The public backfill succeeded: BTCTMN 33,936 rows, BTCUSDT 33,936, USDTTMN 33,895,
from 2023-01-01 00:00 UTC through 2026-11-15 21:00 UTC. There are 33,894 shared timestamps.
All closes are positive. Venue zero-volume candles were retained as the registered script specifies.
Shared data have 23 gaps, at most 10 hours; missing observations were not filled in.
The latest hour may still have been forming; it is after the ranking boundary and was not scored.

```
`implied-toman-rate` implied rate, cost 0.15% per side; 33894 shared hours from 2023-01-01; ranked before 2026-01-01
  24h median,  50 bps:  330 trades, gross   -7.38%, net -106.29%, gross a trade   -2.2 bps, deflated 0.000
  24h median, 100 bps:   38 trades, gross   13.61%, net    2.18%, gross a trade   35.8 bps, deflated 0.018
  24h median, 200 bps:    7 trades, gross    9.42%, net    7.29%, gross a trade  134.6 bps, deflated 0.512
  72h median,  50 bps:  340 trades, gross    3.59%, net  -98.34%, gross a trade    1.1 bps, deflated 0.000
  72h median, 100 bps:   36 trades, gross   11.46%, net    0.64%, gross a trade   31.8 bps, deflated 0.016
  72h median, 200 bps:    9 trades, gross    9.73%, net    7.00%, gross a trade  108.1 bps, deflated 0.400
`implied-toman-rate` VERDICT: FAIL on ranking (best 24h 200 bps, deflated 0.512 on 7 trades); 2026 not scored
```

Arithmetic tests: `tests/test_implied_rate.py`: 4 passed. No change to the rule, costs, split or marks.
No additional trial was selected or fitted, and nothing was sent to an order endpoint.
