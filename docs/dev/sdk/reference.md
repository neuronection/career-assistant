# Reference

The complete lookup surface: error codes, the RPC protocol, the CLI,
the admin API, audit/status vocabularies, host knobs. Tables, not prose.

## Error codes

The closed 15-code typed enum (charter clause 4; `ConnectorError` in
`app/extensions/sdk.py`). Every partial error, sync error and lifecycle
failure is one of these; `detail` is capped data (≤ 500 chars), never a
raw exception dump. `retryable` is closed: `yes | no | after-delay |
after-config-change`.

| Code | Meaning | Typical retryable |
|---|---|---|
| `not-ready` | the runtime isn't injected / the tier is admin-disabled (e.g. `mcp` not allowlisted) | `after-config-change` |
| `needs-secret` | a credentials-required source is missing a sealed slot value | `after-config-change` |
| `invalid` | malformed data: bad rows, bad manifests, plaintext secrets in config, over-cap trees | `no` |
| `unsupported` | the host doesn't do this: kind/tier not hosted, apiVersion too new, unknown RPC method, sandbox unavailable on frozen builds | `no` |
| `io` | local I/O failure | `yes` |
| `not-found` | source/extension/install/ref doesn't exist | `no` |
| `path-denied` | fs-shaped denial in the sandbox; local source outside allowlisted roots / production boot | `no` |
| `net-denied` | SSRF guard, robots verdict, undeclared domain (any hop), private ranges | `no` (posture) |
| `auth` | upstream 401/403 | `after-config-change` |
| `rate-limited` | upstream 429 (Retry-After surfaces as `retry_after_ms`) | `after-delay` |
| `unreachable` | network failure, git fetch failure, tool timeout (T3) | `yes` |
| `protocol` | envelope/protocol violations: not the `{items, next_state}` shape, garbage RPC lines | `after-config-change` |
| `provider` | upstream returned an unusable non-2xx | `yes` |
| `budget` | a quota ran out (concurrency, calls/min, calls/run, bytes/day, state bytes) | `after-delay` |
| `canceled` | the operation was canceled | `no` |

## The capability-RPC protocol (T2 seam, `capability-rpc/1`)

Line-delimited JSON framing (capped by `rpcLineMaxBytes`); every line
validated against the vendored `capability-rpc.schema.json`; typed
error envelopes use the 15-code enum above. The full spec is vendored
at `contracts/capability-rpc.md`. The closed method vocabulary:

| Method | Direction | Purpose |
|---|---|---|
| `ext.invoke` | host → ext | run a tick (`fetch`); `params: {op, config, state}` — identity/digest verified at the `hello` handshake |
| `ext.dispose` | host → ext | graceful shutdown (deadline, then SIGKILL) |
| `cap.net.fetch` | ext → host | the only network path: GET/HEAD, headers ≤ 16, scoped to declared domains every hop, response capped |
| `cap.state.get` / `cap.state.set` | ext → host | extension-owned persisted state (quota `stateMaxBytes` per instance, key-pattern-checked) |
| `cap.items.emit` | ext → host | result rows, schema-validated against the manifest `itemSchema`; invalid batches rejected whole and counted against the error budget |
| `cap.secrets.need` | ext → host | secret resolution **status** — the host substitutes the `{{secret:<slot>}}` placeholder into the next fetch's HEADERS only (URL placeholders are refused typed `invalid`); the value never crosses in any direction — result envelopes and error details are scrubbed of resolved values |
| `evt.progress` | ext → host (event) | `{percent?, messageKey?, payloadBytes?}` — observation, never instruction; rate-capped |
| `evt.log` | ext → host (event) | `{level, message ≤ 500}` — same |

Unknown methods are refused `unsupported` — never dispatched.

## The CLI

Run from `backend/` (`uv run python -m app.extensions.cli …`); exits
non-zero with `code: detail` on typed failure. Secrets are never
accepted on the command line.

| Command | Arguments | Effect |
|---|---|---|
| `source add` | `<descriptor.json>` | add a source (https git, or the gated dev `local` variant) |
| `source list` | — | sources + candidates + installs |
| `source sync` | `<origin-or-id>` | fetch + discover + validate + update-check; exit 1 when the source reports failure |
| `source preview` | `<source> <extension-id>` | host-derived install preview + the exact consent echo (no mutation) |
| `source install` | `<source> <extension-id> --consent-echo <json\|@file>` | consent-gated install; re-derives and refuses drift, mints the disabled instance |
| `source pin` | `<extension-id> --consent-echo <json\|@file>` | apply a recorded available update with its preview echo (the only apply path) |
| `source remove` | `<origin-or-id>` | remove the source; installs park (data + consent intact) |
| `source validate` | `<path-or-url> [--ref strategy=value] [--subpath dir]` | read-only authoring check: descriptor + manifests + host profile |
| `desired-state get` / `put` | `[<document.json>]` | read / write the GitOps desired-state document (admin-owned) |
| `reconcile` | — | run the GitOps reconcile once (same code as boot + hourly) |

## The admin API (import layer)

Under `/api/v1/admin` (admin auth):

| Route | Effect |
|---|---|
| `GET /extensions/sources` | sources with candidates + installs (secret-safe views) |
| `POST /extensions/sources` | add a source (`{descriptor, secrets}`) |
| `DELETE /extensions/sources/{id}` | remove; installs park |
| `POST /extensions/sources/{id}/sync` | sync + update-check |
| `POST /extensions/sources/{id}/install` | `{extension_id, consent}` — consent-gated install (201) |
| `POST /extensions/installs/{id}/apply` | the only apply path (explicit re-consent) |
| `POST /extensions/installs/{id}/enabled` | `{enabled}` — the only enable path |
| `POST /extensions/installs/{id}/park` | park (disabled + flagged) |
| `POST /extensions/installs/{id}/tombstone` | lifecycle `removed`; history retained |
| `GET` / `PUT /extensions/desired-state` | the GitOps document |
| `POST /extensions/reconcile` | reconcile now |

Related surfaces: postings sources live under
`GET/POST /admin/postings/sources` (+ `{id}/probe`, `{id}/sync`),
the connector catalog under `GET /admin/postings/connectors`, mini-app
render views under `GET /extensions/surfaces[/{id}[/export]]` (enabled
installs only — a disabled mini-app's route 404s), and the surface
catalog also feeds the chat tools dialog
(`PUT/DELETE /ai/tools/{key}/grant`).

## Audit vocabulary

One row per external effect on the `ai_generations` funnel:

| Task type | Who writes it | When |
|---|---|---|
| `mcp_tool_call` | the T3 connector (injected `audit`) | every MCP tool call (sync and probe); `prompt` = `mcp:<source-key>:<tool>` |
| `sandbox_capability_call` | the T2 host | every capability call (args hash, outcome, duration, extension id/digest) |
| `tool_run` | the D20 funnel | every chat-tool execution |

Sandbox spawns additionally record `extension_sandbox_runs` rows,
closing with outcome `completed | crashed | watchdog |
protocol-violation | interrupted` (orphans close `interrupted` at boot —
a host restart is never extension failure).

## Status vocabulary

| Surface | Values |
|---|---|
| source status | `ok` \| `degraded` (e.g. digest drift) \| `failing` — with `last_success_at`, `consecutive_failures`, `last_checked_at` |
| install state | `installed` \| `disabled` (parked) \| `self-disabled` \| `removed` (tombstoned) |
| install update state | `current` \| `available` (+ `requiresReconsent`, `manifestDiff`) \| `digest-drift` \| `absent-from-source` |
| reconcile report keys | `installed`, `pinsMoved`, `needsConsent`, `updatesAvailable`, `drift`, `parked`, `failures`, `ignoredEnableIntent` |
| managed by | `manual` \| `gitops` |

## Sandbox knobs

Settings (env `CAREER_EXTENSION_SANDBOX_*`; defaults per the charter):

| Knob | Default | Meaning |
|---|---|---|
| `CAREER_EXTENSION_SANDBOX_ENABLED` | `true` | master kill switch (off ⇒ T2 imports self-disable at spawn) |
| `CAREER_EXTENSION_SANDBOX_CALL_TIMEOUT_SECONDS` | 30 | wall-clock watchdog per call; expiry SIGKILLs ⇒ crash ⇒ self-disable |
| `CAREER_EXTENSION_SANDBOX_SPAWN_TIMEOUT_SECONDS` | 15 | handshake watchdog |
| `CAREER_EXTENSION_SANDBOX_DISPOSE_TIMEOUT_SECONDS` | 5 | graceful dispose deadline, then SIGKILL |
| `CAREER_EXTENSION_SANDBOX_MEMORY_MB` | 512 | address-space cap via `RLIMIT_AS` (POSIX only — see the residuals) |
| `CAREER_EXTENSION_SANDBOX_MAX_CONCURRENT` | 2 | concurrent live sandboxes (over ⇒ typed `budget`) |
| `CAREER_EXTENSION_SANDBOX_CALLS_PER_MINUTE` | 120 | per-extension call rate |
| `CAREER_EXTENSION_SANDBOX_MAX_CALLS_PER_RUN` | 600 | per-run call count |
| `CAREER_EXTENSION_SANDBOX_BYTES_PER_DAY` | 64 MiB | net + items + state bytes/day (process-lifetime bucket) |
| `CAREER_EXTENSION_SANDBOX_EVENTS_PER_RUN` | 120 | progress/log event budget (beyond: dropped, counted) |

## Transport and source knobs

| Knob | Default | Meaning |
|---|---|---|
| `CAREER_CONNECTOR_ALLOWED_HOSTS` | `[]` | bypass the private-range check for trusted self-hosted boards |
| `CAREER_CONNECTOR_ALLOW_PRIVATE_HOSTS` | `false` | wholesale private-host hatch |
| `CAREER_CONNECTOR_BLOCK_PRIVATE_RANGES` | `true` | the SSRF reserved-range block |
| `CAREER_CONNECTOR_PIN_ADDRESSES` | `true` | DNS-rebind TOCTOU pinning |
| `CAREER_CONNECTOR_RESPECT_ROBOTS` | `true` | the robots fail-closed verdict (the remotive escape hatch) |
| `CAREER_CONNECTOR_REQUESTS_PER_MINUTE` | 30 | global ceiling; a connector's lower declared cap wins |
| `CAREER_CONNECTOR_MAX_RESPONSE_MB` | 4 | in-flight response body cap |
| `CAREER_CONNECTOR_READ_TIMEOUT_SECONDS` | 15.0 | read timeout |
| `CAREER_CONNECTOR_MAX_RETRIES` | 3 | full-jitter retries (429/5xx/network) |
| `CAREER_CONNECTOR_PLUGINS_ALLOWLIST` | `[]` | admin opt-in: entry-point plugins + the `mcp` builtin (JSON list, e.g. `["mcp"]`) |
| `CAREER_EXTENSION_LOCAL_SOURCE_ROOTS` | `[]` | allowlisted parents for dev/test `local` sources (JSON list) |
| `CAREER_EXTENSION_FETCH_TIMEOUT_SECONDS` | 60.0 | git subprocess timeout |
| `CAREER_APP_ENV` | `production` | production boots reject local sources (`path-denied`) |

## Registry API (`app/extensions/registry.py`)

`register_connector(connector, *, allow=True)`, `get_connector(key)`,
`resolve_connector(db, key)` (builtins first; any other enabled T2 key
routes through the sandbox runner), `iter_connectors()`,
`list_connectors()`, `reset_registry()` (tests). Entry-point group:
`career_assistant.connectors` (T1 bundled, admin-allowlisted).

## Content caps

| Cap | Value |
|---|---|
| manifest bytes | 512 KiB |
| tree files / bytes | 4096 / 128 MiB |
| T3 items per fetch | 300 |
| T3 `raw` / `next_state` JSON | 8 KiB each |
| consent detail / error detail | 500 chars |
