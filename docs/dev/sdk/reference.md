# Reference

The complete lookup surface: error codes, the RPC protocol, the CLI,
the admin API, audit/status vocabularies, host knobs. Tables, not prose.

## Error codes

The closed 15-code typed enum (charter clause 4; `ConnectorError` in
`app/extensions/sdk.py`). Every partial error, sync error and lifecycle
failure is one of these. `retryable` is closed: `yes | no | after-delay |
after-config-change` — the "typical" column below is the charter
default (`DEFAULT_RETRYABLE` in the polite runtime); an explicit
`retryable` on construction overrides it.

`detail` never carries a raw exception dump. It has two shapes: on the
connector seam `ConnectorError.detail` is a capped string (≤ 500
chars); on the wire — the capability-RPC and lifecycle error envelopes —
it is the bounded **7E object** (`contract.cap_error_detail`), declared
keys only: `message`, `path`, `field`, `id`, `packId`, `runId`, `slot`,
`host`, `hop`, `method`, `op`, `stage`, `engine`, `expected`, `actual`,
`limit`, `used`. Per-key caps apply, the serialized form is capped at
500 chars (`errorDetailMaxChars`), and `message` is the **one**
diagnostic slot — host UI copy is keyed by `code` and may interpolate
the data keys. A bare string on the wire is rejected by the schema.

| Code | Meaning | Typical retryable |
|---|---|---|
| `not-ready` | the runtime isn't injected / the tier is admin-disabled (e.g. `mcp` not allowlisted) | `after-config-change` |
| `needs-secret` | a credentials-required source is missing a sealed slot value | `after-config-change` |
| `invalid` | malformed data: bad rows, bad manifests, plaintext secrets in config, over-cap trees | `no` |
| `unsupported` | the host doesn't do this: kind/tier not hosted, apiVersion too new, unknown RPC method, sandbox unavailable on frozen builds | `no` |
| `io` | OS-level I/O failure on an allowed path (ENOSPC, EIO, EXDEV class) | `no` |
| `not-found` | source/extension/install/ref doesn't exist | `no` |
| `path-denied` | fs-shaped denial in the sandbox; local source outside allowlisted roots / production boot | `no` |
| `net-denied` | SSRF guard, robots verdict, undeclared domain (any hop), private ranges | `no` (posture) |
| `auth` | upstream 401/403 | `after-config-change` |
| `rate-limited` | upstream 429 (Retry-After surfaces as `retry_after_ms`) | `after-delay` |
| `unreachable` | network failure, git fetch failure, tool timeout (T3) | `yes` |
| `protocol` | envelope/protocol violations: not the `{items, next_state}` shape, garbage RPC lines | `after-config-change` |
| `provider` | upstream returned an unusable non-2xx | `yes` |
| `budget` | a quota ran out (concurrency, calls/min, calls/run, bytes/day, state bytes) | `after-config-change` |
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
| `cap.net.fetch` | ext → host | the only network path: **GET only on this host (v1)** — other methods and request bodies are refused typed; headers ≤ 16 (values ≤ 1024), URL ≤ 2048, scoped to declared domains on every hop, ≤ 32 response headers returned, response body capped |
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
| `source validate` | `<path-or-url> [--ref release-tag\|strategy=value] [--subpath dir]` | read-only authoring check: descriptor + manifests + host profile |
| `desired-state get` | — | read the GitOps desired-state document (admin-owned) |
| `desired-state put` | `<document.json>` (required positional) | write it |
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
| `CAREER_MARKET_DATA_PLUGINS_ALLOWLIST` | `[]` | admin opt-in for `career_assistant.market_data` entry-point providers (JSON list) — same opt-in rule as connectors, a separate registry |
| `CAREER_EXTENSION_LOCAL_SOURCE_ROOTS` | `[]` | allowlisted parents for dev/test `local` sources (JSON list) |
| `CAREER_EXTENSION_FETCH_TIMEOUT_SECONDS` | 60.0 | git subprocess timeout |
| `CAREER_DATA_DIR` | platform default | where installs, artifacts and sealed stores live — `<data_dir>/extensions/…` |
| `CAREER_APP_ENV` | `production` | production boots reject local sources (`path-denied`) |

## Dynamic queries (plan 130)

A connector whose engine consumes a per-call search query declares
`ConnectorCapabilities(dynamic_queries=True)`. When a `job_sources` row
is switched to `query_mode='radar'`, `sync_source` merges one call-time
overlay into the config it hands to `fetch()`:

```json
{"query": {"groups": [{"keywords": "<one rotated role group, OR-joined>", "location": "<string>"}], "location": "<string>"}}
```

Contract: the overlay is **call-time only** (never stored; `config` is
not mutated), a batch of up to 3 focused groups per sync (`job_sources.query_batch_size`,
default 1 — radar size never multiplies requests beyond the batch), the
groups are executed **strictly sequentially** by the connector (the
batch sizes the run, never the parallelism), each group's `keywords` is
a focused OR string of one role group, and each group's `location`
overrides on presence (an empty string clears). Connectors without the
capability never see the overlay. The rotation cursor advances by the
batch size. T3 scripts receive it inside the tool's `config`
argument alongside `config.options` (the tool-level settings
passthrough — stored on the source as a JSON-object string, since the
manifest configSchema has no object type, but handed to the tool as a
**parsed object**). The `mcp` connector itself declares the capability —
**every `mcp` source, including managed imports, can *Follow my
radar***; no manifest field is needed, the source form offers the
switch and the overlay arrives inside the tool's `config`. The merged-query artifact (role groups, term→radar
provenance, rotation cursor) lives in `job_sources.query_cache` and is
rebuilt on radar change by the `query_curator` background job (Layer 2:
an AI-curator task that clusters keywords; the deterministic Layer 1
partition is the fallback whenever AI is unconfigured).

## Detail enrichment (the `detail_ids` contract)

A connector whose source has a per-posting detail page (the full job
description behind the list row) can let the host schedule those
fetches. The host reads exactly two config names — everything else
about the mode stays connector-owned:

| Config name | Read by the host as |
|---|---|
| `detail_mode` | `off` (default) · `sample` · `smart` · `all` — the source's enrichment mode |
| `detail_limit` | 1–10 (default 5) — detail pages per run |

Both are read from the top-level config **and** the `options`
passthrough layer (managed-spawn sources keep bundle knobs in
`config.options`). A connector that declares these fields in its
`configSchema` gets the whole pipeline:

- **`sample`** — the connector's own business: enrich the newest
  `detail_limit` rows inline, inside the same sync call.
- **`smart` / `all`** — the sync stays list-only. The host ranks the
  not-yet-detailed postings (`all`: every new posting; `smart`: a
  deterministic Layer 1 score of radar-keyword match, seniority/onsite
  agreement, a stated salary and recency — plus an optional AI re-rank
  in the background job when AI is configured) and calls `fetch` again
  with a **call-time overlay**: `config.detail_ids` — a comma-joined
  list of at most 10 `external_id`s — with `detail_mode` forced to
  `"off"`. On such a call the connector fetches exactly those ids'
  pages, returns those rows (with `raw.description` plus any typed
  fields the page states), round-trips `state` untouched, and runs no
  search.
- Batching is paced: one batch (≤ `detail_limit` ids) per enrichment
  run, one enrichment run queued per sync. A posting's detail fetch is
  retried across runs and gives up after 3 attempts
  (`detail_fetched_at` / `detail_attempts` on the posting row).
- Merge semantics: only fields the detail page actually states are
  merged — list-derived fields are never wiped; typed fields fill gaps.
  A fetched description resets the posting's earlier AI extraction so
  the deep pass (`POSTING_EXTRACT`) re-runs on the full text.

The enrichment call rides the same connector seam (`registry.resolve_connector`
→ `fetch`), the same audit funnel and the same validation caps as any
other call — there is no privileged path.

## Run summary (`run_summary`)

A fetch envelope may carry `run_summary` beside
`items`/`next_state`/`partial_errors`: **any JSON object, ≤ 2 KB
serialized**, validated shape-agnostically and persisted verbatim on
the run ledger (`source_runs.report.run_summary`). The source's run
drawer renders the keys it knows (version the block with a `schema`
int; `schema: 1` is current):

| Key | Renders as |
|---|---|
| `mode` | the run's session posture — `"authenticated"` renders as authenticated, any other string as guest |
| `launches` | process/browser launches by kind (`{"guest": 1, "authenticated": 0}`) |
| `navigations` | page loads by kind (`{"search_pages": 2, "detail_pages": 5}`) |
| `budget` | `{"limit_s", "search_used_s", "detail_used_s"}` — a split bar plus a used/limit line |
| `walled_skips` | ids the run could not fetch behind an auth wall (expandable list — the emitter keeps it small; the host caps only the block size) |

Unknown keys persist but render nothing; a summary asserting none of
the known keys renders nothing at all. An oversize or non-object
summary is dropped with a typed `invalid` partial error. Envelopes
without the block (and bundles on older versions) look exactly as
before — the block is optional on every tier that speaks the envelope.

`budget.limit_s` is the **emitter's own declared soft budget** — a
`configSchema` field (conventionally `budget_seconds`) the connector
self-enforces through admission control and merely reports here; the
host's only wall around it is the source's `timeout_seconds` (5–120),
so keep the declared budget comfortably under it (the reference
bundles ship `timeout ≥ budget + 30`).

## Probe semantics

The admin **Test** (probe) endpoint treats **any** partial error as
not-ok, even when the fetch itself succeeded — a run over a feed with
known skippable items (say, items walled behind a sign-in) reports the
typed partials and reads as a failed test while the source is healthy.
Check the partial detail before diagnosing: an expected-condition
partial is not a fault. Syncs are unaffected (partials degrade, they
never fail a sync).

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
| T3 `raw` JSON | 64 KiB |
| T3 `next_state` JSON | 8 KiB |
| T3 `run_summary` JSON | 2 KiB |
| extension state per instance | 256 KiB |
| capability-RPC line | 1 MiB |
| consent detail / error detail | 500 chars |

## The docs-truth gate

This doc set is pinned to the law it describes: `backend/tests/test_sdk_docs_truth.py`
turns doc drift into a test failure — the runnable-examples rule ("a
code block that lies is a bug") made mechanical:

| Pin | What fails it |
|---|---|
| every manifest printed in this set | materialized as a bundle and run through `contract.validate_registration` — the vendored envelope, the entry/docs/i18n semantics and this host's profile — so a block that would not install fails the suite |
| the verbatim claims | the template manifest block in [Authoring & Configuration](authoring-and-configuration.md#the-manifest-reference) must equal `backend/tests/fixtures/mcp_template_manifest.json`, and the Arbeitnow block in [Examples](examples-and-use-cases.md#recipe-1--a-t1-builtin-connector) must equal `app/extensions/builtin/arbeitnow/manifest.json` |
| the [error table](#error-codes) | a code or `retryable` default that differs from `contracts/extension-charter.json` or the runtime's `DEFAULT_RETRYABLE` |
| the [RPC method table](#the-capability-rpc-protocol-t2-seam-capability-rpc1) | a method `runtime/sandbox/protocol.py` does not speak |
| the [knobs tables](#sandbox-knobs) | a `CAREER_*` knob the extensions subsystem reads and this page omits — or a documented knob that no longer exists in `Settings` |
| the [capabilities table](authoring-and-configuration.md#the-capabilities-table) | a capability this host honors and the chapter never names |

Structure is walled separately: `test_extension_docs_tree.py` validates
this set's `docs-tree.json` against the vendored docs-tree contract, and
`test_connector_docs_api.py` owns the per-extension docs surface. When
the law moves, the docs move in the same commit — the gate is what makes
"same commit" checkable when only one side moves.

Fence convention behind the first pin: a printed manifest is held to the
**imported** rules unless its fence is tagged ```` ```json bundled ````
(recipe 1's T1 manifest is the one such block). Tag it — otherwise the
block is held to the imported-connector `entry` rule and fails as it
should.
