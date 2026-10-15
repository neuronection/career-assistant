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

## Extension sources & the import layer (T3 from git)

`app/extensions/lifecycle.py` is the D24 home for sources, consent,
pins and GitOps (ADR-0040 D13/D15/D22). One pipeline, two modes:

- **manual** — an admin adds a source in Settings → Tools → Connectors
  (or via the CLI below), reviews the discovered extensions and
  consents per extension;
- **GitOps** — an admin-owned desired-state document (the
  `extensions.desired_state` AppSetting, validated against the vendored
  `desiredStateDocument` schema) reconciled at boot and hourly
  (`system_extension_reconcile` → `extension_reconcile` job).

### The pipeline

`resolve → shallow fetch → discover manifests (subpath + one level) →
schema-validate against the vendored envelope → host-profile compat →
per-extension consent → pinned install`. Concretely:

- **Descriptors** validate against the vendored
  `extension-sources.schema.json`: production descriptors are **https
  git URLs only** (ssh/`file://`/userinfo are structurally
  inexpressible). The dev/test **`local`** variant
  (`$defs.localSourceDescriptor`, `local.path` replacing `url`) serves
  the sibling template repo and dogfood checkouts: absolute paths only,
  no `..` segments at the seam, **gated off in production boots**
  (fail-closed: `CAREER_APP_ENV=production` rejects local sources with
  `path-denied`) and **confined to `CAREER_EXTENSION_LOCAL_SOURCE_ROOTS`**
  — the clone root must resolve under an allowlisted parent
  (net_guard-style path discipline).
- **Host profile (career)**: connector-kind imports only (mini-app
  surfaces arrive with Phase 4; bridge is server-class), `extension/v1`
  with `kindVersion ≤ 1`, capabilities ⊆ `{sync, secrets}` — an
  imported T3 script's own sockets are consent-disclosed, never granted
  as `net` (D22). The runnable entry is `server.py` beside the manifest
  (the template shape); no entry ⇒ typed `unsupported`.
- **Digest + pin**: sha256 over the extension dir (deterministic file
  walk, regular files only, adversarial caps). Content lands
  content-addressed under `data_dir/extensions/<id>/<digest>/` — DATA,
  never importlib'd, never on `sys.path` (the structure probe enforces
  both).
- **The install mints a disabled `mcp` job source** whose stdio command
  spawns `<interpreter> <content>/server.py` — the managed spawn from
  the cloned content (D13). Enabling is a separate explicit act.

### Consent (what every import shows)

Per-extension consent BEFORE any install, naming: **capabilities**,
**tier + import class**, **provenance** (`author`/`license`/
`repository`/`description` verbatim from the manifest), the pinned
**digest**, and the T3 perimeter disclosure **verbatim** (see the copy
in the script-tier section above — it renders from the vendored charter,
never paraphrased). Consent records persist on the install (who/when/
what-digest) and survive tombstoning. **Capability growth or tier change
on update re-consents** (the browser-permission model).

### Updates — no signatures, no auto-apply

An install records its source ref + content digest. Update check = ref
move + digest change + manifest diff:

- identical digest at a moved ref ⇒ the pin moves (nothing consented
  changed);
- digest change ⇒ an update is *offered* (`state: available`,
  `requiresReconsent`) — applying it is an explicit re-consent call,
  always. **There is no auto-apply path at all** (no signing service
  exists); T0 data diffs would auto-apply only on a byte-identical
  manifest (capabilities + configSchema unchanged);
- **digest drift on a pinned ref** (the same tag/commit now yields
  different content — the supply-chain attack signal) ⇒ LOUD failure:
  the install flags `digest-drift`, the source degrades, pins stay
  untouched; never a silent refetch.

### GitOps reconcile — pins only, never data

Reconcile (boot + hourly + on demand) reads the desired-state document
and:

- moves pins **only for the extensions the list names** — manual
  installs are never re-pinned or removed (drift is reported as status);
- never auto-enables — the entries' `enabled` field is acknowledged and
  ignored (consent is the gate, the list is only a pin-mover);
- never deletes data — deletion is structurally inexpressible in the
  desired-state schema; removal from the list parks gitops-managed
  installs **disabled + tombstone-able**, content and consent records
  intact;
- installs an entry only when a consent record already exists at that
  exact digest (e.g. a tombstoned install) — otherwise it reports
  `needsConsent`;
- leaves pins untouched on a failed fetch and marks the source
  `failing` (the family status vocabulary with
  `last_success_at`/`consecutive_failures`).

Private-repo credentials are **secret-slot references** — the sealed
value resolves host-side into the git subprocess environment
(`GIT_CONFIG_*`, never argv, never logs); an inline token is
structurally invalid at the schema seam.

### The CLI

```bash
cd backend
uv run python -m app.extensions.cli source add descriptor.json
uv run python -m app.extensions.cli source list
uv run python -m app.extensions.cli source sync <origin-or-id>
uv run python -m app.extensions.cli source install <origin> <extension-id> --consent
uv run python -m app.extensions.cli source pin <extension-id> --consent   # apply a recorded update
uv run python -m app.extensions.cli source remove <origin-or-id>
uv run python -m app.extensions.cli source validate <path-or-url> [--ref branch=main] [--subpath dir]
uv run python -m app.extensions.cli desired-state get | put <doc.json>
uv run python -m app.extensions.cli reconcile
```

`source validate` is the authoring helper: it runs the descriptor +
manifest + host-profile checks read-only (fetching local paths), so a
repository owner can verify their extension imports cleanly before
sharing the git URL. Secrets never cross the command line — supply
credential slot values through the admin API or the settings UI.

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
