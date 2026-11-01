# TradingGYM stop-only pipe, wire protocol v1

This is only the T0 emergency control wire contract. It does not grant money permissions. The transport is a local Windows named pipe with an OS-enforced DACL and remote-client rejection. Untrusted senders cannot self-declare a more privileged principal.

Every message is exactly 40 bytes, a single message-mode pipe frame:

| Offset | Width | Field | Encoding |
| --- | --- | --- | --- |
| 0 | 8 | Magic | ASCII `TGSTOP01` |
| 8 | 2 | Version | `1`, unsigned big-endian |
| 10 | 2 | Length | `40`, unsigned big-endian |
| 12 | 1 | Code | Request: `1 STATUS`, `2 PAUSE_ENTRIES`, `3 EXIT_ONLY`, `4 HALT`; reply: `128 ACK`, `129 STALE_RUNTIME` |
| 13 | 1 | Mode | Request: 0; reply: `0 DISARMED`, `1 PAUSED`, `2 EXIT_ONLY`, `3 HALTED` |
| 14 | 1 | Changed | Request: 0; reply: 0 or 1; stale reply must be 0 |
| 15 | 1 | Reserved | 0 (other values rejected) |
| 16 | 8 | Runtime epoch | Nonzero, unsigned big-endian; replies carry the service's current epoch |
| 24 | 16 | Correlation ID | Nonzero 16-byte opaque identifier; echoed exactly in replies |

Reject unknown command codes, malformed frames, trailing data, zero runtime identities, unsupported versions and response codes sent as requests. The protocol contains no ARM, FLATTEN, CANCEL, ORDER, CAP or PROVISION command. STATUS never changes state; stop transitions only increase restrictiveness. HALT also prevents automatic protective exits, not just entries. Restart resets to DISARMED and replaces the epoch.

An ACK proves only that the Executor applied the atomic mode gate; it is not proof that an exchange order was canceled or any exit filled. The UI must show a request as pending until the correctly correlated ACK arrives. A missing ACK must not be reported as success. Stale-epoch responses carry the current epoch; callers re-fetch status rather than replaying old commands.

The Windows listener DACL grants SYSTEM and the exact Executor service SID full control, the operator's logon SID only data read/write plus synchronize (0x00100003), and explicitly denies NETWORK. Generic write is forbidden because it grants FILE_CREATE_PIPE_INSTANCE. Always use PIPE_REJECT_REMOTE_CLIENTS and FILE_FLAG_FIRST_PIPE_INSTANCE on the first listener.

Wire authentication is the OS DACL, not a field in this frame. SID provenance, service identity, DACL/credential self-tests, and the dedicated host are separate mandatory acceptance work. This byte-level contract does not establish funded readiness.
