# Research design

Extend the native paper engine and point-in-time portal. Keep one owner for each
calculation and journal; source breadth does not justify a second runtime,
credential store, frontend or execution authority.

## Working contracts

- Decisions use closed data available at their cutoff. Missing periods reset
  readiness; later observations cannot repair what was known earlier.
- Exact accounting follows actual simulated holdings, fee currencies, nonfills
  and working remainders. Reference feeds and FX have separate availability clocks.
- Comparisons match data, costs, cash and baselines. Portfolio replay instead
  shares cash and cannot be summed from independent-account results.
- Every exploratory trial and failure remains recorded. Chronological selection,
  purged evaluation and final evaluation have distinct meanings.
- A local consume-once registry prevents ordinary re-use of a final window; it
  does not establish independent custody or supply future observations.
- Model interpretations remain advisory. Exact cited arithmetic can be verified
  without treating prose, a repository or a backtest as trading permission.

Use [research workspace contracts](research-workspace.md) for request fields,
bounds and unknown states, [architecture](architecture.md) for owners,
[metrics](metrics.md) for statistical limits and the
[implementation plan](implementation-plan.md) for remaining deliverables.
