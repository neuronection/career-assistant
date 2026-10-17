# Authoring & Configuration

The manifest is the law; the code implements it. This chapter is the
field reference for writing connectors at every tier, plus the mapping
guidance the three real job boards established. The SDK surface lives in
`backend/app/extensions/sdk.py`; every code block here is code that runs
in this repo or its walls.

## The manifest reference

Every connector — bundled or imported — validates against the vendored
envelope (`contracts/extension-manifest.schema.json`) **at registration
or discovery**; an invalid manifest never enters the registry. The
minimal copy-paste-valid imported manifest (the template repo's, which
the wall `test_template_manifest_validates_against_the_vendored_envelope`
pins):

```json
{
  "apiVersion": "extension/v1",
  "kindVersion": 1,
  "kind": "connector",
  "id": "example-posting-fetcher",
  "version": "1.0.0",
  "description": "Reference posting fetcher for career-assistant: an external MCP server (T3 script tier) whose fetch_postings tool returns validated RawPosting rows. The script process runs outside the app's network perimeter by design (ADR-0040 clause 21).",
  "author": "Neuronection",
  "license": "MIT",
  "repository": "https://example.com/your-fork/career-connector-template",
  "categories": ["data"],
  "capabilities": ["sync"],
  "configSchema": {
    "type": "object",
    "properties": {
      "board": {
        "type": "string",
        "title": "Board slug",
        "description": "Which board this source fetches (handed to fetch_postings as config.board)",
        "maxLength": 120
      }
    },
    "required": ["board"]
  },
  "itemSchema": {
    "type": "object",
    "properties": {
      "external_id": { "type": "string", "title": "External id" },
      "title": { "type": "string", "title": "Title" },
      "org": { "type": "string", "title": "Organization" },
      "url": { "type": "string", "title": "URL" }
    },
    "required": ["external_id", "title"]
  },
  "supportsIncremental": true,
  "i18n": {
    "defaultLocale": "en",
    "locales": { "en": { "title": "Reference posting fetcher", "summary": "An external MCP script that feeds postings to career-assistant." } }
  }
}
```

Field reference (envelope `extension/v1`, connector refinement):

| Field | Required | Meaning |
|---|---|---|
| `apiVersion` | ✔ | `"extension/v1"` — the envelope scheme (mini-apps instead carry the ADR-0029 integer `apiVersion: 1`) |
| `kindVersion` | ✔ | `1` today; a host with a lower refinement self-disables the import typed `unsupported` |
| `kind` | ✔ | `"connector"` (imports of kind `mini-app` follow the ADR-0029 shape; `bridge` is server-class, not hosted) |
| `id` | ✔ | stable id; the install's instance key and content dir name |
| `version` | ✔ | your semver |
| `description` | ✔ | ≤ 400 chars, rendered on the consent surface |
| `author`, `license`, `repository` | ✔ | provenance, rendered verbatim at consent |
| `categories` | ✔ | charter category slugs (e.g. `data`) |
| `capabilities` | ✔ | closed list ⊆ what the host honors for your tier (see the table below) |
| `domains` | if `net` | the declared-domain scope — every fetch hop (redirects included) must land in it |
| `configSchema` | ✔ | JSON Schema for the instance config (drives the settings form; may mark `x-secret`) |
| `defaults` | – | default instance config for T2 installs; must satisfy `configSchema` incl. its `required` |
| `secrets` | – | declared secret slots beyond x-secret fields: `[{id, purpose}]` |
| `itemSchema` | ✔ | the flat `RawPosting` record (`external_id` + `title` required at minimum) |
| `supportsIncremental` | ✔ | must match reality — the conformance kit tests capability honesty |
| `i18n` | ✔ | `defaultLocale` + `locales` label map (the family string rule) |
| `tools` | if `chat-tools` | chat-tool declarations; every entry's `riskClass` is schema-required |

### The capabilities table

| Capability | Grants | Risk class tie-in |
|---|---|---|
| `sync` | run on the posting sync schedule | — |
| `net` (+ `domains`) | fetch through the host's polite runtime, scoped to `domains` on every hop | the runtime enforces politeness; the author declares the scope honestly |
| `state` | extension-owned persisted state (quota'd, T2 via `cap.state.*`) | — |
| `secrets` | secret slots resolved host-side (never cross to the sandbox/tool) | secrets are at-rest-sealed; values exist only host-side per fetch |
| `ui:page` / `ui:panel` / `ui:window` | declarative surfaces (mini-app kind; window degrades to page on this host) | — |
| `run` | the typed-action funnel (`run:export`) | — |
| `chat-tools` (manifest `tools` list) | contributes chat tools to the assistant | every tool carries `read-only \| state-changing \| destructive` — the invocation funnel enforces it |

Host-honored subsets at import: T3 connectors ⊆ `{sync, secrets}` (a
script's own sockets are disclosed, never granted); T2 connectors ⊆
`{sync, net, state, secrets}`; mini-apps ⊆ `{report, run}` + the
honored `ui:*` set.

### configSchema and the x-secret law

Instance config is declared as a JSON Schema and stored validated on the
`job_sources` row. **A field marked `"x-secret": true` never stores its
value in config**: values ride the source's `secrets` payload and land
at-rest-sealed in `job_sources.secrets`. A plaintext secret inside
`config` is a registration-time throw (HTTP 400 /
`ValidationError` from `validate_config`) — never stored, never echoed.
The admin API surfaces slot presence and a `…last4` hint only; `***` on
update preserves the stored value, an empty string clears it. At sync
time the host decrypts slots and injects them into
`fetch(config, state, *, transport, secrets)`; a credentials-required
connector with a missing slot surfaces the typed `needs-secret` error —
never a silent empty fetch. Migration `0047` moved the one legacy
plaintext credential into the sealed store.

The `mcp` connector's config schema is the worked example — `token`
(the optional Bearer for the http transport) is an `x-secret` field:

```python
MCP_CONFIG_SCHEMA = {
    "type": "object",
    "properties": {
        "transport": {"type": "string", "title": "Transport", "enum": ["stdio", "http"], "default": "stdio"},
        "command": {"type": "string", "title": "Stdio command line (e.g. python /path/to/server.py)", "maxLength": 1000},
        "url": {"type": "string", "title": "HTTP server URL", "maxLength": 1000},
        "tool": {"type": "string", "title": "Fetch tool", "default": "fetch_postings", "maxLength": 120},
        "allowed_tools": {"type": "string", "title": "Tool allowlist (comma-separated; empty = just the fetch tool)", "maxLength": 1000},
        "timeout_seconds": {"type": "number", "title": "Tool timeout (seconds)", "minimum": 5, "maximum": 120, "default": 30},
        "token": {"type": "string", "title": "Bearer token (optional, http transport)", "maxLength": 500, "x-secret": True},
    },
}
```

### The declared-domains honesty rule

`net` requires `domains`, and the polite runtime checks **every hop** —
redirects included — against that list. Declare exactly the hosts you
fetch from: a CDN redirect chain is fine if the final host is declared;
an undeclared hop is typed `net-denied`. Never widen `domains` to work
around a failure — that is a config problem, not a scope problem.
Connectors whose fetch targets are **user-configured** URLs (`rss`,
`jsonld`, `csv`, `manual_url`, the sandbox's instance config) declare
`sync` only: their scope is the validated instance config, guarded
per-fetch host-side.

## `RawPosting` — the only output type

Every connector emits `RawPosting` rows: normalized, **pre-taxonomy**
data. `skills_raw` are free-text mentions that core maps onto the skills
ontology — the connector never guesses taxonomy ids. Field caps are
enforced by the model (`external_id`/`title` ≤ 300, `org` ≤ 200,
`url` ≤ 1000, `skills_raw` ≤ 60 entries, `raw` is an arbitrary bag but
T3 caps it at 8 KB per row). Dates are timezone-aware UTC; salary is
`SalarySpec` (ISO-4217 + range + period) only when honestly parseable;
`seniority`/`employment_type`/`onsite_policy` use their closed enums
only where the source is unambiguous. The result envelope is
`ConnectorResult` — `{items, next_state, partial_errors}` — and every
partial error is a typed `ConnectorError` (see the
[Reference](reference.md#error-codes) table), never a string.

**Mapping guidance** (established by the real boards, pinned by
`backend/tests/test_job_board_connectors.py` against captured wire
fixtures):

- **Stable identity**: a board's `slug`/`id` → `external_id`; rows
  without one are typed `invalid` and never persist.
- **Employment type**: map free-text onto the enum only where
  unambiguous — `freelance → contract`, `Werkstudent → part_time`;
  German indefinite contracts stay unmapped. Ambiguity is better than a
  wrong enum.
- **Salary**: Remotive ships free-text strings; `parse_salary_text`
  parses `"$170k - $200k"`, `"$50-$75 /hour"`, `"$35,3k- $52k"` (a `k`
  suffix makes commas decimals). Unparseable → `None`, never a guess.
  Jobicy ships structured `salaryMin/Max/Currency/Period` — use it
  directly.
- **Remote**: both remote-jobs boards set `remote=True` with the geo
  restriction preserved (`raw.location_note` / `location.country`).
- **Watermark incremental**: stamp the oldest returned posting's date
  into `next_state.watermark`, drop at-or-below items next sync;
  conditional-GET validators ride the same `next_state` (a 304 is "no
  news", not an error); changed content still dedups downstream by
  `content_hash`.

## The three real connectors as worked T1 examples

`backend/app/extensions/builtin/job_boards.py` ships Arbeitnow, Remotive
and Jobicy — free, no-auth public JSON APIs verified against live
captures (fixtures in `backend/tests/fixtures/connectors/` are the wire
truth). Their manifests declare **no secret slots by absence** — zero
config, `{}` validates — with optional filters and polite caps:

| Connector | Endpoint | Declared domains | rpm | Config (all optional) |
|---|---|---|---|---|
| `arbeitnow` | `https://www.arbeitnow.com/api/job-board-api` | `www.arbeitnow.com` | 10 | `tags` (≤16), `max_items` 1–300 (default 100) |
| `remotive` | `https://remotive.com/api/remote-jobs` | `remotive.com` | 10 | `category`, `max_items` 1–500 (default 100) |
| `jobicy` | `https://jobicy.com/api/v2/remote-jobs` | `jobicy.com` | 12 | `tag`, `max_items` 1–200 (default 50; ≤3 pages walked, ≤100/page) |

The Arbeitnow connector is the ~90-line shape worth copying — config
model + schema, honest manifest, one `fetch` through the injected
transport, watermark state, typed errors:

```python
class ArbeitnowConfig(BaseModel):
    tags: list[str] = Field(default_factory=list, max_length=16)
    max_items: int = Field(default=100, ge=1, le=300)

ARBEITNOW_URL = "https://www.arbeitnow.com/api/job-board-api"
ARBEITNOW_DOMAINS = ("www.arbeitnow.com",)


class ArbeitnowConnector(PostingConnector):
    key = "arbeitnow"
    title = "Arbeitnow job board"
    capabilities = ConnectorCapabilities(
        network_scopes=list(ARBEITNOW_DOMAINS),
        supports_incremental=True,
        max_requests_per_minute=10,
    )

    def config_model(self) -> type[BaseModel]:
        return ArbeitnowConfig

    def manifest(self) -> dict:
        return connector_manifest(
            manifest_id="career-arbeitnow",
            title="Arbeitnow job board",
            description="Live German/European job board through the public job-board-api "
            "(free, no credentials — no secret slots by design).",
            config_schema=ARBEITNOW_CONFIG_SCHEMA,
            capabilities=["net", "sync"],
            domains=list(ARBEITNOW_DOMAINS),
            supports_incremental=True,
        )

    async def fetch(self, config, state, *, transport=None, secrets=None, **_kw) -> ConnectorResult:
        cfg = ArbeitnowConfig.model_validate(config)
        if transport is None:
            return _not_ready()
        resp = await transport(ARBEITNOW_URL, conditional_headers(state or {}))
        if resp.status == 304:
            return ConnectorResult(next_state=merge_cache_state(state, resp.etag, resp.last_modified))
        if resp.status == 429:
            return ConnectorResult(partial_errors=[_rate_limited("arbeitnow", resp.headers)])
        if resp.status != 200:
            return ConnectorResult(
                partial_errors=[_provider_error(f"arbeitnow fetch failed with status {resp.status}")]
            )
        items, row_errors = parse_arbeitnow_payload(resp.body)   # + typed protocol guard
        if cfg.tags:
            ...  # normalized tag filter
        items = _apply_watermark(items, state or {})
        items = _sort_and_cap(items, cfg.max_items)
        return ConnectorResult(
            items=items,
            next_state=_stamp_watermark(state or {}, items, resp.etag, resp.last_modified),
            partial_errors=row_errors,
        )
```

(The full file also carries the parser, the shared watermark helpers and
the other two boards; the conformance suite
`test_job_board_connectors.py` subclasses the vendored kit per board.)

**The remotive robots story (recorded deviation).** `remotive.com/robots.txt`
carries `Disallow: /api/*`, and the charter's fail-closed robots law
means the polite runtime denies live remotive fetches under the default
posture — surfaced as a typed `net-denied` (the fixture wall pins
exactly this against the captured robots body). An operator who judges
their use consistent with Remotive's API terms (which explicitly welcome
API consumers) can lift it per deployment via the
`CAREER_CONNECTOR_RESPECT_ROBOTS` escape hatch — a deliberate admin
decision, never a connector-side bypass. Never code around robots in a
connector; the runtime owns that verdict.

The same manifests ship as adoption data in the sibling
`career-connector-template` repo (`connectors/` — the bundle is the
contract: other hosts can adopt them where career bundles the T1
implementations).

## Writing a connector (T1, step by step)

1. Subclass `PostingConnector` with a unique `key`.
2. Define `config_model()` (a pydantic model) and return validated JSONB
   from `validate_config`.
3. Implement `fetch(config, state, *, transport, secrets, audit)` to
   emit `RawPosting`s and update `next_state`. Treat `transport` as
   required — without it, return a typed `not-ready` error, never an
   empty success. Mark credential fields in the manifest's
   `configSchema` with `"x-secret": true`; values arrive via the
   `secrets` mapping, never through stored config.
4. Provide a `fixture_payload` so the contract tests run offline.
5. Declare a truthful `manifest()` (capabilities, `domains` when `net`,
   `supportsIncremental` matching reality).
6. Register it (built-in) or ship it as a deployment-image entry point
   (plugin, admin allowlist). External distribution is T2/T3 — see the
   [recipes](examples-and-use-cases.md).

Test with the vendored conformance kit
(`app/extensions/conformance.py`, `ConnectorConformanceTests`): config
round-trip, idempotency, external_id stability, typed partial errors,
capability honesty and conditional-GET forwarding — all offline.

## Authoring at T2 and T3

- **T3 (external MCP script)**: ship a repo with `manifest.json` +
  `server.py` exposing one tool, `fetch_postings(config, state) ->
  {items, next_state}`. Everything you return is untrusted and validated
  app-side (required `external_id`/`title`, http(s) URLs, char caps, a
  300-item cap, 8 KB `raw`/`next_state` caps). The template repo's
  `server.py` is the complete example —
  [recipe 2](examples-and-use-cases.md#recipe-2--a-t3-mcp-script-connector).
- **T2 (sandboxed module)**: ship `manifest.json` + `extension.py` with
  `def fetch(config, state) -> dict`, speaking only the vendored
  `capability` module (`net_fetch`, `state_get`/`state_set`,
  `items_emit`, `secrets_need`, `progress`, `log`). The frozen module
  surface (json, re, math, decimal, statistics, datetime, itertools,
  functools, collections, heapq, bisect, string, textwrap, unicodedata,
  random) is enforced by an audit hook — no sockets, no files, no
  environment. The reference fixture is the complete example —
  [recipe 3](examples-and-use-cases.md#recipe-3--a-t2-sandboxed-connector).
- At both tiers the manifest `configSchema` drives the settings form,
  and `defaults` (T2) seed the instance config — they must satisfy the
  schema or the install rejects typed `invalid`.
