"""TradingGYM gym-core (Zone A): collector, rules, local API. No order transport: order modules here are dry-run contracts and read-only parsers."""

import os as _os

if _os.environ.get("GYM_RUST_KERNEL") == "1":  # ADR 0005: opt-in Rust money rules; missing module is an error
    import exec_kernel as _exec_kernel

    from .domain import sim as _sim
    _sim.use_kernel(_exec_kernel)
