# Native order admission

Admission consumes an exact, unexpired, prepared operator ticket once. It checks
the current arm lease, credential/runtime and installation units, current native
fees and book, and two matching durable balance receipts. The quote limit includes
buy fees and rounding. Raw pair availability enters the hold book once; executor
holds are subtracted once rather than being counted twice.

Sell admission uses inventory computed from the executor's complete own fills.
An external deposit supplies no position or cost basis. It reserves the quantity
plus the maximum observed fee in base units, rounded up, so even an outgoing-base
fee is covered. A new journal event records that extra hold; older reservation
bytes retain their exact replay interpretation.

Synthetic regressions cover the durable admission, exact native request body,
thirteen refusal cases without consuming the review, expiry/stop before an effect,
fee rounding, sell inventory, and holds surviving an uncertain send and restart.
These tests place no real orders and do not qualify an installed host. The next
branch connects a separate elevated command and fixed-origin venue transport.

The native request uses the documented `client_id` field. The local
[Wallex reference](../../../gym-core/docs/wallex-reference.md) records the newer Swagger
contract; the [official older reference](https://api-docs.wallex.ir/) independently
documents that field and the LIMIT endpoint. No private venue call was made.
