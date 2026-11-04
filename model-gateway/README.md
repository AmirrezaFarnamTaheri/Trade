# Optional advisory model gateway

Requires Node >=22.19.0. Dependency: public `@earendil-works/pi-ai` pinned to `1.5.0` (MIT, Mario Zechner). No donor code or private Pi auth storage is used.

The local workspace now has an **AI connections** screen. Add a named provider
connection, choose API key or supported browser sign-in, then sync model presets.
OpenAI's current browser sign-in is under **OpenAI**; the separate Codex entry is
the SDK's legacy provider. Actual account entitlements remain provider-dependent.
Requests remain disabled until explicitly enabled; sending a prompt is a separate
action and can incur provider charges. No test prompt runs automatically.

Browser-added API connections use `{"type":"api_key","env":[],"stored":true}`.
Stored key pools use the existing private credential database and Windows
current-user DPAPI, in namespaces distinct from OAuth. Configuration exports
contain references, never key values, and export disabled. Existing environment
key pools keep working; OAuth never falls back to API keys. The browser's masked
key field replaces the stored pool for that connection, and deletion leaves
environment keys untouched. Non-Windows private-file plaintext storage remains
explicitly disclosed. Do not enter venue keys in this model-provider screen.

`control.mjs` reuses native state/config/runtime ownership. `host.mjs` accepts
bounded correlated JSON lines only from the Python application's private stdin;
it opens no new control port. OAuth sessions expose only a short-lived ID,
provider URL, device code and current prompt. Cancellation and app shutdown
terminate the pending flow. Provider diagnostics/tokens are never returned as
errors. See [workflow ownership](../gym-core/docs/architecture.md).

```sh
cd model-gateway
npm ci --ignore-scripts
npm test
node gateway.mjs providers
node gateway.mjs catalog openai
```

After installing the Node dependency, the Python entry point forwards these commands without loading the gateway into the collector:

```powershell
uv run --project gym-core gymctl models providers
uv run --project gym-core gymctl models catalog openai
uv run --project gym-core gymctl models catalog anthropic
uv run --project gym-core gymctl models config import models.json
uv run --project gym-core gymctl models login chatgpt
uv run --project gym-core gymctl models status
```

These commands run from the repository root. The Python launcher also selects its own Python executable for the Windows DPAPI helper. If invoking Node directly on Windows for OAuth, set `GYM_MODEL_PYTHON` to the absolute path of your Python executable first. A source checkout is required; the optional JavaScript component is not bundled in a Python wheel.

For ChatGPT browser sign-in, use connection `{"id":"chatgpt","provider":"openai","auth":{"type":"oauth"}}`; for Anthropic, use `{"id":"claude","provider":"anthropic","auth":{"type":"oauth"}}`. Put these in the configuration's `connections` array and choose matching model IDs from each catalog for the presets. API-key connections instead use `{"type":"api_key","env":["OPENAI_API_KEY","OPENAI_API_KEY_2"]}` (or the corresponding provider's variables). Keys are environment values, never JSON fields. OAuth never falls back to those keys automatically.

From the repository root, replace `node gateway.mjs` below with `node model-gateway/gateway.mjs`.

## CLI

All normal output is JSON on stdout. Errors are generic JSON on stderr and exit 1. OAuth instructions go to stderr. Only `complete` authorizes a paid model request; it also requires `enabled: true`.

```text
providers
catalog <sdk-provider-id>
config import <json-file>
config show
presets export [new-file]
presets import <json-file>
presets sync <connection-id>
login <connection-id> [--device]
logout <connection-id>
status
complete <preset-id>
```

`complete` reads only `{"prompt":"..."}` from stdin. The JSON envelope is limited to 70 KiB, decoded prompt to 64 KiB UTF-8, and stdin plus request share the configured deadline. No tools, conversation history, attachments, account state or market data are accepted. Output includes text, usage, selected model/connection/preset, `mode: "RESEARCH_ONLY"`, and `funded_authority: false`. `usage.costSource` distinguishes `SDK_CATALOG_ESTIMATE`, `PROVIDER_REPORTED`, and `UNKNOWN`; unknown costs are `null`, never a zero-price claim. Catalog estimates are not invoices. Returned model metadata identifies its source and is never marked provider verified; custom endpoints have null context, output-capacity and capability metadata, even when the model ID matches a built-in model. `requestOutputTokens` and `gatewayOutputCeiling` describe gateway request policy, not server capacity.

## Schema 1

Example custom API-key endpoint configuration (HTTPS required outside explicitly opted-in loopback tests):

```json
{
  "schema": 1,
  "enabled": false,
  "policy": { "maxAttempts": 3, "timeoutMs": 30000 },
  "connections": [{
    "id": "research-api",
    "provider": "my-compatible-provider",
    "protocol": "openai-completions",
    "baseURL": "https://models.example.com/v1",
    "auth": { "type": "api_key", "env": ["RESEARCH_KEY_1", "RESEARCH_KEY_2"] }
  }],
  "presets": [{
    "id": "research",
    "name": "Research",
    "connection": "research-api",
    "model": "explicit-upstream-model-id",
    "maxTokens": 1024,
    "temperature": 0.2
  }]
}
```

For a built-in provider, omit both `protocol` and `baseURL`, and use its SDK ID and a catalog model ID. OAuth uses `"auth": {"type":"oauth"}`; it requires a built-in OAuth provider and forbids both endpoint/protocol overrides. Missing credentials and failed refresh never resolve ambient API keys. No inline key, header, tool, command, executable, credential path or extra schema fields are accepted.

- Missing `enabled` defaults to false. Missing policy defaults to 3 attempts / 30000 ms. Attempts: 1–3; timeout: 100–120000 ms.
- At most 100 connections, 100 env references per API connection, 5000 presets, 1 MiB configuration. IDs: `[a-zA-Z0-9][a-zA-Z0-9_.-]{0,99}`. Env names: `[A-Z_][A-Z0-9_]{0,127}`.
- Preset `name`, `maxTokens`, `temperature`, and `catalog` are optional. Model IDs/names are nonempty, bounded to 200 characters without control characters. Max output: 1–65536 tokens, additionally bounded by the SDK cap when known; default request cap is min(1024, model cap). Temperature: 0–1 for Anthropic Messages, 0–2 otherwise; SDK model-specific omissions still apply.
- `catalog` contains only `name`, `api`, `contextWindow`, `maxTokens`, `reasoning`; it is offline SDK display metadata, not executable routing or provider verification. Runtime preserves built-in model capabilities/compatibility flags. Unknown custom models send text input with reasoning disabled. Their SDK adapter uses zero as the unknown-context sentinel and numeric zero prices only to satisfy the SDK cost calculator; those placeholder prices are replaced with null in returned usage unless the provider explicitly reported a cost. The 65536-token ceiling is gateway policy; the actual server context/output capacity, supported capabilities and price remain unknown. Configure an appropriate request cap for the actual server.
- Custom protocols: `openai-completions`, `openai-responses`, `anthropic-messages`. Runtime also supports the SDK's built-in legacy `openai-codex-responses` over SSE. Other protocols fail closed with `unsupported_protocol`. Listing a provider is not a guarantee that all its protocols or extra tenant configuration are supported.

`config import` validates fully before atomic replacement and does not import/change credentials. Preset exports contain the same portable configuration schema, forcibly disabled, with env **names**, never key values or OAuth credentials. Export to a file refuses overwrite. Preset import merges, preserves the current enablement/policy, and rejects connection changes or preset identity collisions. Sync is offline: it appends missing SDK catalog models and updates only `catalog` metadata for existing connection/model rows, retaining names, output caps, endpoints, custom rows and credentials. It does not fetch provider-specific dynamic catalogs.

## Private state and rotation

State defaults to `%LOCALAPPDATA%/TradingGYM/models` on Windows, `$XDG_STATE_HOME/tradinggym/models` or `~/.local/state/tradinggym/models` on POSIX. `GYM_MODEL_HOME` overrides the directory for isolation. Symlinks/junctions are rejected; POSIX requires current-user ownership and 0700/0600 permissions. Windows installs a current-user-only DACL, including existing state files. The same OS account is trusted; this is not a sandbox against that account.

Windows OAuth bytes pass through the fixed sibling helper `gym-core/src/gym/adapters/model_credentials.py` using the executable named by `GYM_MODEL_PYTHON`, which the parent Python launcher sets to `sys.executable`. Only raw stdin/stdout carry credential bytes; helper failures are generic. Windows OAuth is DPAPI current-user encrypted in SQLite. POSIX credentials are private plaintext, **not encrypted**. Unit-test seal/unseal injection is code-only, never configuration. No ambient Pi auth is read.

SQLite `BEGIN IMMEDIATE` spans the entire async credential refresh callback; rollback and process-death release are tested. Credential namespaces are connection/provider pairs. API keys are resolved from configured env names on every completion, deduplicated by value, and never persisted. SQLite persists an HMAC fingerprint, round-robin cursor and invalid/cooldown state scoped to connection/provider/model/protocol/endpoint. Removed/empty value pools discard old health. Value changes get fresh health.

401/auth-invalid evicts a value; 429 or explicitly quota-coded 403 cools it. Permission 403 and other permanent 4xx are fatal. Retry-After/reset headers are honored when exposed, otherwise cooldown is 60 seconds; all-cooling pools fail without early reuse. 5xx/network errors use bounded backoff. No account/provider/model/endpoint fallback occurs. SDK retries are set to zero; a fetch guard permits one HTTP request per gateway attempt, redirects are refused, and all attempts share cancellation/deadline. Stream errors discard buffered partial text and are not replayed. Response streams are capped at 2 MiB and returned text at 1 MiB.

For local tests only, `GYM_MODEL_ALLOW_LOOPBACK_HTTP=1` admits explicit HTTP URLs on localhost, 127.0.0.1 or ::1. Never use that switch to weaken a production endpoint policy.

## Verification and limits

The `node:test` suite uses actual SDK implementations against local OpenAI Completions, OpenAI Responses and Anthropic SSE servers. It covers durable unique-value round robin, 429 exhaustion, auth eviction, changed/removed pools, quota-vs-permission 403, transient retries, bounded/cancelled requests and stdin, stream errors, malformed/unknown/inline-key refusal, default-disabled behavior, sync preservation, real CLI subprocesses, SQLite rollback, SDK refresh serialization across processes, process-death unlock, missing/failed OAuth with ambient keys present, and Windows real DPAPI ciphertext roundtrip/corruption refusal. Windows junction refusal runs without symlink privilege; the file-symlink test is skipped when that privilege is unavailable.

Local execution was on Windows with Node v26.1.0 and Python 3.11.9. Node 22/Linux compatibility is targeted by the package engine and parent CI, not claimed as locally executed. No live OAuth login, provider refresh, subscription entitlement, paid request or remote model endpoint was tested. `--device` selects the SDK device flow only for legacy `openai-codex`; current `openai` ChatGPT OAuth is browser/manual-callback only in SDK 1.5.0. OAuth support does not assert compliance with subscription terms. Built-in catalogs and estimated prices can be stale; custom endpoint pricing remains unknown without an explicit provider-reported cost.
