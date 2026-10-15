# Extensions (connector SDK)

Posting sources are a **registry extension point** — the only way to add
one — and the registry is career's convergence to the family extension
charter (ADR-0040; `app/extensions/` per the D24 subsystem home). This
page is the authoring guide and this host's profile. The family law lives
in [the charter](https://neuronection.dev): kinds, tiers, capabilities,
the typed error model, the `{items, next_state, partial_errors}` result
envelope.

## The contract

`app/extensions/sdk.py` defines the whole surface:

- **`RawPosting`** — the only type a connector may emit. It is normalized
  and **pre-taxonomy**: `skills_raw` are free-text mentions that core maps
  to the skills ontology. It carries title, org, location, url, dates,
  salary, seniority, employment/contract type, onsite policy, work hours,
  travel, education and an arbitrary `raw` bag.
- **`ConnectorResult`** — the charter result envelope: `items`,
  `next_state` (the opaque incremental cursor; conditional-GET validators
  ride it) and `partial_errors` as **typed charter errors**
  (`ConnectorError`: one of the 15 closed codes + capped detail + closed
  `retryable`). Never strings, never raw exception dumps.
- **`ConnectorCapabilities`** — network scopes, whether credentials are
  required, incremental support, `max_requests_per_minute` and whether URL
  fetching is allowed.
- **`PostingConnector`** — the protocol: `key`, `title`, `docs_url`,
  `capabilities`, `fixture_payload`, `config_model()`, `manifest()`,
  `fetch(...)` and `validate_config(...)`.
- **`manifest()`** — the connector-kind extension manifest
  (`apiVersion: extension/v1`, `kind: connector`, `kindVersion: 1`),
  validated against the vendored envelope schema
  (`contracts/extension-manifest.schema.json`) **at registration** — an
  invalid manifest never enters the registry. `itemSchema` is the flat
  `RawPosting` record; `net` requires its declared `domains`.

## The transport runtime (politeness is enforced, not documented)

Connectors **never open sockets themselves**. `sync_source` injects the
polite HTTP transport built app-side (`app/extensions/runtime/http.py`)
over the vendored family runtime (`app/extensions/polite_http.py`,
ADR-0040 D5):

- **SSRF guard** — resolve-then-connect with the checked address pinned
  into the request (DNS-rebind TOCTOU mitigation), reserved/loopback/
  link-local/private ranges blocked, numeric IPv4 obfuscations (decimal,
  octal, short forms) coerced and checked, and **every redirect hop
  re-validated**. This closes the 2026-09-11 audit's connector-URL
  finding.
- **robots.txt** — fetched and cached per host through the same guarded
  transport; a robots 5xx or any failure to obtain a verdict **denies**
  the fetch (fail-closed).
- **Rate caps** — per-host token buckets sized by each connector's
  declared `max_requests_per_minute` (the global
  `CAREER_CONNECTOR_REQUESTS_PER_MINUTE` is the ceiling).
- **Conditional GET** — etag/last-modified round-trip through
  `next_state`; 304 responses mean "nothing new", not an error.
- **Retries** — full-jitter backoff on 429/5xx/network errors (60 s
  ceiling), RFC 7231 `Retry-After` honored in both forms (the 429 payload
  surfaces as `retry_after_ms`); 401/403 fail immediately as typed
  `auth`.
- **Size caps** — response bodies are capped in flight
  (`CAREER_CONNECTOR_MAX_RESPONSE_MB`).

Escape hatches (trusted self-hosted boards on a LAN, private-range
policy, pinning, robots) are `CAREER_CONNECTOR_*` Settings — never raw
environment reads — and default to the closed posture. The hostile wall
(`contracts/polite_http.fixtures.json`, run by
`backend/tests/test_extensions_contract.py`) pins all of this.

## Built-in engines

`app/extensions/builtin/__init__.py` ships first-party connectors:

| Key | Engine | Manifest declares |
|---|---|---|
| `ats_api` | Public applicant-tracking-system job APIs (Greenhouse / Lever / Ashby) | `net` scoped to the three ATS API domains |
| `jsonld` | `schema.org/JobPosting` structured data | `sync` (instance-scoped guard) |
| `rss` | Job feeds | `sync` |
| `csv` | Exported spreadsheets | `sync` |
| `manual_url` | A single posting you point at | `sync` |
| `mcp` | The T3 script tier (external MCP servers) — [below](#the-script-tier-t3--external-mcp-servers) | `sync` + `secrets`, **no `net`** (T3 perimeter) |

Connectors that fetch **user-configured** URLs declare `sync` only: their
network scope is the validated instance config, and the host-side guard
(fail-closed, robots, caps) applies per fetch. Connectors with statically
known endpoints declare `net` + `domains` and every hop — redirects
included — is checked against that scope.

## The script tier (T3 — external MCP servers)

External authors ship **scripts**, not plugins: an MCP server whose
`fetch_postings(config, state)` tool returns the family result envelope
(`{items, next_state}`). The `mcp` builtin connector maps such a server
to a posting source — ADR-0040 D9, MCP-first. Reference authoring repo:
`career-connector-template` (the family sibling template — clone, edit
`_rows()`, register). Client construction stays in `app/ai/mcp_client.py`
(ADR-0012; the structure probe pins fastmcp to the AI layer).

**Off by default.** The connector registers only when
`CAREER_CONNECTOR_PLUGINS_ALLOWLIST` names `mcp` — allowlist-off means
it is invisible in the catalog and unknown to the registry (structural,
tested). One source = one server + ONE tool: `transport` (`stdio`
command line or `http(s)` url), `tool` (default `fetch_postings`),
`allowed_tools` (per-tool allowlist, comma-separated — the configured
tool must be in it), `timeout_seconds` (5–120, default 30) and an
optional `token` (x-secret slot; the http transport's Bearer header).

**The T3 perimeter (consent copy, verbatim — ADR-0040 clause 21):**

> This extension runs as a separate process outside the app's network
> perimeter. It opens its own network connections, with no SSRF guard,
> robots.txt check or rate limiting by the app. The app governs only
> what it returns: outputs are validated and capped.

That is why the connector's manifest declares **no `net` domains** —
the script's own sockets are not a host-side capability — and why the
host governs only the output: every returned row is validated app-side
against `RawPosting` (required `external_id`/`title`, http(s) `url`s,
char caps, a 300-item cap, an 8 KB `raw`/`next_state` size cap) before
anything persists; malformed rows become typed `invalid` partial errors,
envelope violations typed `protocol` errors, and every tool call lands
on the audit funnel as one `mcp_tool_call` row (through the injected
`audit` callback — the same `ai_generations` funnel the MCP bridge
uses). Secrets never cross to the script: the optional token is
resolved host-side for the transport, and the config handed to the tool
is stripped of declared secret slots. A tool that outlives its timeout
fails its own source with a typed `unreachable` error — the sync path
and other sources keep running.

**The model never authors this tier** (ADR-0011 §7 / ADR-0030 §6): no
model output may register, enable or schedule a script source; source
registration is an admin act against the catalog UI. Phase 3 adds
git-link import on top (the template repo is the first git source).

**Frozen builds (desktop packaging):** stdio spawns ride the mcp SDK's
`get_default_environment()` through fastmcp — PATH is preserved while
the rest of the environment is sanitized, so spawned scripts resolve
their interpreters inside PyInstaller bundles. The release smoke tests
include one stdio MCP source sync in the frozen app (see
[desktop-packaging](desktop-packaging.md)).

## The plugin registry

`app/extensions/registry.py`:

- Built-ins auto-register at import; every registration validates the
  manifest against the vendored envelope schema (the capability gate —
  violations throw at registration, never mid-run).
- Entry-point plugins arrive via the group
  `career_assistant.connectors` and are **admin-opt-in** via
  `CAREER_CONNECTOR_PLUGINS_ALLOWLIST`. That path is **T1 bundled only**
  (ADR-0040 clause 2): entry-point plugins are code shipped in the
  deployment image. External authors write T3 MCP connectors (the script
  tier, plan 32 Phase 2), never in-process plugins.
- `register_connector`, `get_connector`, `list_connectors` are the API;
  `reset_registry` exists for tests.

A plugin that is not allowlisted is simply not registered.

## Secrets (the x-secret law)

Connector credentials never live in `job_sources.config`. Fields marked
`"x-secret": true` in a connector's manifest `configSchema` (plus the
manifest `secrets` list) declare **secret slots**; values ride the
source's `secrets` payload and land **atrest-sealed** in
`job_sources.secrets` (the `ai_providers.api_key_encrypted` discipline —
settings-map INV-4). A plaintext secret inside `config` is a
**registration-time throw** (HTTP 400 from the admin API, `ValidationError`
from `validate_config`) — never stored, never echoed. The admin API
returns slot presence and a `…last4` key hint, never the sealed value and
never plaintext; `***` in an update preserves the stored secret, an empty
string clears it. At sync time the host decrypts the slots host-side and
injects them into `fetch(config, state, transport, secrets)`; a
credentials-required connector with a missing slot surfaces the typed
`needs-secret` error (sync + probe), never a silent empty fetch.
Migration `0047` moved the one legacy plaintext credential (ats
`api_token`) into the sealed store and stripped it from config.

## Writing a connector

1. Subclass `PostingConnector` with a unique `key`.
2. Define `config_model()` (a pydantic model) and return validated JSONB
   from `validate_config`.
3. Implement `fetch(config, state, *, transport, secrets)` to emit
   `RawPosting`s and update `next_state`. Treat `transport` as required —
   without it, return a typed `not-ready` error, never an empty success.
   Mark credential fields in your manifest's `configSchema` with
   `"x-secret": true`; values arrive via the `secrets` mapping (sealed
   slots), never through stored config.
4. Provide a `fixture_payload` so the contract tests run offline.
5. Declare a truthful `manifest()` (capabilities, domains when `net`,
   `supportsIncremental` matching reality).
6. Register it (built-in) or ship it as a deployment-image entry point
   (plugin, admin allowlist).

## Testing

`app/extensions/conformance.py` (the vendored family kit) provides
`ConnectorConformanceTests` — subclass it per connector: config
round-trip, idempotency, external_id stability, typed partial errors,
capability honesty and conditional-GET forwarding, all offline. The
runtime's own politeness and the D23 hostile list are pinned by
`backend/tests/test_extensions_contract.py` against the vendored fixtures.

## Related

- [Data model](data-model.md) — `job_sources`, `job_postings`
- [AI layer](ai-layer.md) — the posting extraction pass that runs after ingest
- [Adding features](adding-features.md#add-a-connector) — the recipe
- [Architecture](architecture.md) — the D24 extension home
