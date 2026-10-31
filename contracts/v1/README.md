# Executor contracts v1 (preliminary)

The canonical envelope is described in TradingGYM_Master_Specification_and_Plan.md
sections 5.2 and 13.1. The fixture here fixes the exact stored bytes used in
the hash-chain golden test; it does **not** yet establish the complete
cross-process event schema.

Funded order payloads, proposal messages and authorization command formats
must be specified, versioned, and verified across Rust/Python before IPC
or funding is enabled. All money JSON fields must be exact decimal strings.
