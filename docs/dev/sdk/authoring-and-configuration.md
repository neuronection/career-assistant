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
the template repo's manifest, reproduced verbatim — its byte-stable
twin is `backend/tests/fixtures/mcp_template_manifest.json`, which
`test_fixture_manifest_matches_the_canonical_template` pins to
`career-connector-template/manifest.json` (the `server.py` twin beside
it is pinned by `test_fixture_copy_matches_the_canonical_template`).
Every manifest printed in
this doc set is materialized as a bundle and run through the vendored
registration law by `backend/tests/test_sdk_docs_truth.py`, so no block
here can drift from the contract:

```json
{
  "apiVersion": "extension/v1",
  "kindVersion": 1,
  "kind": "connector",
  "id": "example-posting-fetcher",
  "version": "1.0.0",
  "description": "Reference posting fetcher for career-assistant: an external MCP server (T3 script tier) whose fetch_postings tool returns validated RawPosting rows. The script process runs outside the app's network perimeter by design (ADR-0040 clause 21).",
  "docs": "docs/docs-tree.json",
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
  },
  "entry": "server.py",
  "mcp": { "transport": "stdio" }
}
```

Field reference (envelope `extension/v1`, connector refinement). The
schema is closed (`additionalProperties: false`) — an unknown field is a
registration throw, not a silently ignored hint. Constraints below are
the charter's `limits`; hosts may tighten, never loosen.

| Field | Required | Meaning & constraints |
|---|---|---|
| `apiVersion` | ✔ | `"extension/v1"` — the envelope scheme (mini-apps instead carry the ADR-0029 integer `apiVersion: 0\|1`) |
| `kindVersion` | ✔ (connector/bridge) | integer `0`–`1`; a host with a lower refinement self-disables the import typed `unsupported` |
| `kind` | ✔ | `"connector"` (imports of kind `mini-app` follow the ADR-0029 shape; `bridge` is server-class, not hosted) |
| `packKind` | mini-app | `assessment \| surface` |
| `id` | ✔ | pattern `^[a-z][a-z0-9-]{2,39}$`; stable id — the install's instance key and content dir name. Reserved prefixes `host-`/`neuro-` are rejected |
| `title` | – | ≤ 80 chars — the human display name surfaces show ("LinkedIn"); optional, hosts fall back to the id. Imported connector sources carry it as the source's display name. Presentational only: not part of the consent-triggering diff (capabilities/configSchema), though a title edit still changes the bundle digest — tier re-consent law applies as for any content change |
| `version` | ✔ | your semver, `^\d+\.\d+\.\d+(-[0-9A-Za-z.-]+)?$` |
| `description` | – | ≤ 400 chars, rendered on the consent surface |
| `entry` | ✔ (imported connector) | the code declaration: ≤ 255, relative to the bundle root, no `..`, a regular non-symlink file inside the bundle, extension `.py` on this host (`entryExtensions` is charter data). **Tier is provenance here**: `entry` alone ⇒ T2, `entry` + `mcp` ⇒ T3, no `entry` ⇒ T0. The `extension.py`/`server.py` filenames are the template repo's convention, not a rule |
| `mcp` | – | `{ "transport": "stdio" }`, connector-only; declares the external MCP process (⇒ T3) and therefore requires `entry` |
| `docs` | – | `"docs/docs-tree.json"` — the only value the schema admits; when present the tree must exist beside it and validate (see [shipping your own docs bundle](#shipping-your-own-docs-bundle)) |
| `author`, `license` | ✔ | ≤ 120 each; provenance, rendered verbatim at consent |
| `repository` | – | ≤ 512, https only, no userinfo |
| `categories` | – | ≤ 3 unique charter slugs — the closed 8: `files`, `data`, `search`, `productivity`, `utilities`, `developer`, `home`, `learning` |
| `capabilities` | ✔ | 1–16 unique, closed vocabulary ⊆ what the host honors for your tier/kind (see the table below) |
| `domains` | if `net` | 1–16 hostnames or `*.` wildcards (≤ 253 chars) — the declared-domain scope; every fetch hop (redirects included) must land in it |
| `tools` | if `chat-tools` | 1–24 chat-tool declarations `{id, riskClass, titleKey, descriptionKey}`; `riskClass` is schema-required |
| `configSchema` | – | flat JSON Schema for the instance config (≤ 64 properties, depth ≤ 3, field types `string\|number\|boolean\|array`, `pattern`s must be timeout-safe) — drives the settings form; may mark `x-secret`. Nothing at the seam demands it, but every real connector ships one |
| `defaults` | – | ≤ 64 properties; must satisfy `configSchema` incl. its `required` |
| `secrets` | – | declared secret slots beyond x-secret fields, ≤ 16: `{id, purpose (≤ 200), domains (1–16)}` — an imported T2 manifest with `net` + `secrets` must bind `domains` per slot |
| `privacy` | – | `{sendsContent, sensitiveGlobs (≤ 256 × ≤ 200), contentCapBytes 0–8192}` |
| `i18n` | ✔ | `defaultLocale` + `locales` (≤ 16) label map (the family string rule); `title` 1–80, `summary` ≤ 200, values ≤ 400 chars / ≤ 400 keys per locale; the default-locale `title` is required |
| `icon` | – | data-URL `png\|jpeg\|webp` base64 only, ≤ 64 KB (SVG is structurally rejected) |
| `itemSchema` | ✔ (connector) | the flat `RawPosting` record (≤ 64 properties; `external_id` + `title` required at minimum) |
| `supportsIncremental` | ✔ (connector) | must match reality — the conformance kit tests capability honesty |
| `contributions`, `run`, `report`, `liveCard`, `surfaces`, `data` | mini-app | the ADR-0029 declarative surface refinement: `report.nodes` 1–96 (each ≤ 8 keys), `surfaces` maps `page\|panel\|window` to a report, `data` ≤ 24 keys, `run` ≤ 8, `liveCard` ≤ 4, `contributions` ≤ 8 |

Whole-manifest cap: 512 KiB. Requiredness is per kind — the envelope
rules add the conditional rows above (`entry` for imported connectors,
`domains` for `net`, `tools` for `chat-tools`, `itemSchema` +
`supportsIncremental` + `kindVersion` for connectors). The law itself
is `contracts/extension-manifest.schema.json` + `contracts/extension-charter.json`
in this repo; when this table and the schema ever disagree, the schema
wins and this table is the bug.

### The capabilities table

| Capability | Grants | Risk class tie-in |
|---|---|---|
| `sync` | run on the posting sync schedule | — |
| `net` (+ `domains`) | fetch through the host's polite runtime, scoped to `domains` on every hop | the runtime enforces politeness; the author declares the scope honestly |
| `state` | extension-owned persisted state (quota'd, T2 via `cap.state.*`) | — |
| `secrets` | secret slots resolved host-side (never cross to the sandbox/tool) | secrets are at-rest-sealed; values exist only host-side per fetch |
| `ui:page` / `ui:panel` / `ui:window` | declarative surfaces (mini-app kind; window degrades to page on this host) | — |
| `run` | the typed-action funnel (`run:export`) | — |
| `report` | a declarative report surface rendered by the host from the closed component vocabulary (mini-app kind) | — |
| `chat-tools` (manifest `tools` list) | contributes chat tools to the assistant | every tool carries `read-only \| state-changing \| destructive` — the invocation funnel enforces it |

Host-honored subsets at import: T3 connectors ⊆ `{sync, secrets}` (a
script's own sockets are disclosed, never granted); T2 connectors ⊆
`{sync, net, state, secrets}`; mini-apps ⊆ `{report, run}` + the
honored `ui:*` set.

**The family vocabulary is wider than any one host's.** The charter
(`contracts/extension-charter.json` → `capabilities`) declares 23 ids;
the envelope admits 18 for imported manifests and all 23 for bundled
ones. This host (charter `hostProfiles` → `career-assistant`) honors
ten — `net`, `sync`, `secrets`, `state`, `chat-tools`, `report`,
`run`, `ui:page`, `ui:panel`, `ui:window` — checked with per-tier and
per-kind precision (`honorsByTier`: T1 ⊆ `{net, sync, secrets,
chat-tools}`, T2 ⊆ `{net, sync, secrets, state}`, T3 ⊆ `{sync,
secrets}`; `honorsByKind["mini-app"]` = `{report, run, ui:page,
ui:panel, ui:window}`). The rest of the family vocabulary — `fs-read`,
`fs-write-quarantine`, `fs-write-mutate` (reserved), `decision`,
`llm`, `propose`, `notify`, `push`, `ui:chat-card`, `ui:settings`,
`ui:custom-code`, `inbound-webhook`, `inbound-api` — is honored by
other hosts (health, study, desktop) or reserved. Declaring one here is
not a warning: the manifest self-disables at registration with
"capabilities not honored by this host profile". `ui:window` is the one
honored-but-degrading id — it renders as a page on this web host (the
degrade is charter data, never a code branch).

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

**Required fields are enforced at save time for T3 managed sources**
(plan 173): the mcp `options` passthrough is checked against the bundle
manifest's `configSchema` whenever the source is created, its config is
saved, its query mode changes, or it is enabled — a missing or empty
required field (e.g. `keywords`) is a 400 naming the field, not a sync
that fails later inside the bundle. Radar-mode sources relax
`keywords`/`location` (the radar query overlay supplies them per sync),
mirroring the T2 `validate_config` rule. Only required fields gate:
optional knobs stay free-form (the settings forms store numbers as
strings; the tool's own validation coerces them).

### Form hints (`x-choices`, `x-csv`, `x-presets`, `x-section`)

Beside `x-secret`, the configSchema admits four rendering hints the
host's settings form understands (schema law:
`contracts/extension-manifest.schema.json` → `configField`; they change
how a field renders, never what is stored beyond what their
`$comment`s say):

| Hint | On | Shape / constraint | Renders as |
|---|---|---|---|
| `x-choices` | field | array ≤ 24 of `{value ≤ 64, label ≤ 80}` | toggle chips (multi-select) |
| `x-csv` | field | `true` | the stored value is the comma-joined string of the selected `x-choices` values, in choices order |
| `x-section` | field | string ≤ 40 (e.g. `"advanced"`) | the field groups under a collapsed section |
| `x-presets` | configSchema | array ≤ 8 of `{label ≤ 80, values: ≤ 16 string props}` | one-click starting points above the fields; the form merges the values |

A worked fragment — a chips field (multi-select stored as CSV), a
field grouped under a collapsed section, and a schema-level preset:

```json
{
  "seniority": {
    "type": "string",
    "title": "Seniority",
    "description": "Pick the levels to include — chips toggle on/off.",
    "maxLength": 120,
    "x-choices": [
      { "value": "internship", "label": "Internship" },
      { "value": "entry", "label": "Entry level" },
      { "value": "mid_senior", "label": "Mid-senior" }
    ],
    "x-csv": true
  },
  "pause_between_pages": {
    "type": "number",
    "title": "Pause between page loads (seconds)",
    "minimum": 2,
    "maximum": 15,
    "default": 2.5,
    "x-section": "advanced"
  }
}
```

The admin form renders `seniority` as toggle chips; the stored value
(and what the tool then receives in `config`) is the comma-joined
string of the selected values in choices order. At the `configSchema`
level, one-click starting points render above the fields:

```json
{
  "x-presets": [
    { "label": "Internships", "values": { "seniority": "internship" } }
  ]
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

### Shipping your own docs bundle

The optional `docs` pointer is the one field that binds a whole second
contract. `"docs": "docs/docs-tree.json"` is the only value the schema
admits; when it is present, the referenced tree **must exist beside it
and validate** — a pointer without a valid tree fails exactly like an
invalid manifest (the install self-disables). A manifest without the
pointer simply ships no docs.

The tree is the per-extension form (`extensionDocsTree`):

```json
{
  "version": 1,
  "categories": [
    { "category": "overview", "items": [
      { "id": "overview", "title": "Overview", "description": "What the extension is and when to use it.", "file": "overview.md" }
    ] },
    { "category": "troubleshooting", "items": [
      { "id": "troubleshooting", "title": "Troubleshooting", "description": "Symptom, cause, fix.", "file": "troubleshooting.md" }
    ] }
  ]
}
```

- **Categories are a closed seven** — `overview`, `setup`, `usage`,
  `reference`, `security`, `changelog`, `troubleshooting` — each entry
  keyed `category`, at most once per tree. Free-form category strings
  are structurally rejected; display labels come from the entry's
  `title`/i18n/the title-cased slug. Closed ≠ mandatory: list exactly
  the categories you have real pages for (a page that fits none of the
  seven is a family vocabulary question, never a free-form string).
- **Items carry `id`, `title`, `description` and `file`** (all
  required; `id` stable and unique across the tree) plus the optional
  `audience`, `index`, `locales`. Pages are markdown beside the tree
  (`file` is relative to `docs/`), and **markdown only — no raw HTML**:
  hosts strip it fence-aware before rendering, so a `<script>` is at
  best a validation failure and at worst inert escaped text. Raw HTML
  is never a layout tool here.
- **The landing rule**: array order is render order, and the first item
  of the first category is the landing page — unless exactly one item
  anywhere sets `"index": true` (two claims is a contradiction).
- **Locale siblings** follow the page-locale convention: `<page>.md` is
  the default-locale page; translations live beside it as
  `<page>.<locale>.md`, noted in the item's `locales` array. A noted
  locale without its sibling is a broken promise (fails like a missing
  `file`). Hosts serve best-locale → default and say which they served.
- **Optional item `audience`** tags (`user` or `dev`) route readers;
  they never gate access.
- **No per-extension changelog file and no `docs/v2/`** — the docs'
  versioning rides the manifest `version`, always.

Skeleton: `templates/extension-docs/` in the `career-connector-template`
sibling repo (all seven categories as honest stubs, with a fill
procedure). The filled-in precedent is the template
repo's two reference extensions (`example-posting-fetcher`,
`cv-gallery`) — and note that every manifest printed in this doc set is
checked against this contract by the
[docs-truth gate](reference.md#the-docs-truth-gate).

## `RawPosting` — the only output type

Every connector emits `RawPosting` rows: normalized, **pre-taxonomy**
data. `skills_raw` are free-text mentions that core maps onto the skills
ontology — the connector never guesses taxonomy ids. The model
(`app/extensions/sdk.py`) enforces the caps below; fields not listed do
not exist, and unparseable data is `None`, never a guess. Two
constraints bite outside the model and are marked in the table: `url`
must be http(s) (the row-validation seam checks it, not the model) and
dates should be timezone-aware UTC (naive values are accepted and
coerced downstream):

| Field | Type | Cap / constraint |
|---|---|---|
| `external_id` | str | 1–300 — the source's stable id (required; rows without one are typed `invalid` and never persist) |
| `title` | str | 1–300 (required) |
| `org` | str | ≤ 200 — the raw organization label; core normalizes it into the org entity, you never create one |
| `url` | str | ≤ 1000; http(s) only — enforced at the row-validation seam, not the model |
| `location` | `LocationSpec` | `{city, country, remote}` — every part optional, `remote` defaults `false` |
| `salary` | `SalarySpec` | `{currency, min, max, period, basis}` — `currency` 3 chars (default `USD`), `min`/`max` ≥ 0, `period` ∈ `hour\|day\|week\|month\|year` (default `year`), `basis` ∈ `gross\|net` only when the posting says so (else NULL); set only when honestly parseable |
| `seniority` | enum | `intern\|junior\|mid\|senior\|lead\|principal` |
| `employment_type` | enum | `full_time\|part_time\|contract\|temporary\|internship` |
| `contract_type` | str | ≤ 60 free text (e.g. `permanent`, `fixed-term`) |
| `onsite_policy` | enum | `onsite\|hybrid\|remote` |
| `work_hours` | str | ≤ 60 free text (shift patterns, schedule cues) |
| `hours_per_week_min` / `hours_per_week_max` | number | ≥ 0 |
| `travel_class` | str | ≤ 60 free text |
| `education_level` | str | ≤ 40 free text — degree names differ per country; leave the source's wording, core maps it |
| `skills_raw` | list[str] | ≤ 60 entries — skill mentions before taxonomy mapping |
| `posted_at`, `expires_at` | datetime \| null | prefer timezone-aware UTC — naive datetimes are accepted and coerced downstream |
| `raw` | object | the source's own payload — an arbitrary bag, but T3 caps it at 64 KB per row |

The three enums are closed (`SeniorityLevel`, `EmploymentType`,
`OnsitePolicy` in `sdk.py`): map free text onto them only where
unambiguous, and set a closed enum never for "probably".

The result envelope is `ConnectorResult` — `{items, next_state,
partial_errors}` — and every partial error is a typed `ConnectorError`
(see the [Reference](reference.md#error-codes) table), never a string.
`next_state` is yours and opaque to the host (capped at 8 KB at T3; the `raw` bag's cap is 64 KB — sized for full, untruncated job descriptions).

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

## The connector surface (`PostingConnector`)

What the base class gives you (`sdk.py`) beyond `fetch`:

| Member | Role |
|---|---|
| `key`, `title` | the registry key and display title |
| `config_model()` | your pydantic config model (drives `validate_config`) |
| `fetch(config, state, *, transport, secrets, audit)` | one sync tick → `ConnectorResult` |
| `capabilities: ConnectorCapabilities` | declared operational constraints — `network_scopes`, `requires_credentials`, `supports_incremental`, `max_requests_per_minute`, `url_fetching`. The runtime enforces them; the conformance kit checks honesty |
| `fixture_payload` | the captured wire payload for offline contract tests |
| `manifest()` / `manifest_file` | the bundle's `manifest.json` (a FILE at the bundle root, never code-declared); out-of-tree entry-point plugins override `manifest_file` with their shipped path |
| `secret_slots()` | the D19 merge: `configSchema` fields marked `x-secret` **plus** the manifest `secrets` list → `{slot id: purpose}` |
| `chat_tools()` | chat-tool contributions (D20) — must agree with the manifest `tools` list; the registration bridge cross-checks both directions |
| `audits_effects` + the `audit` parameter | connectors that cause effects outside the injected transport (the T3 tier) set this; sync/probe then receive an `audit` callback and every external effect lands on the audit funnel |

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

    # The manifest lives in builtin/arbeitnow/manifest.json — a FILE at
    # the bundle root (the family form, never code-declared):

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
5. Author the bundle's `manifest.json` at
   `backend/app/extensions/builtin/<key>/manifest.json` — a FILE (the
   family form, never code-declared), validated at registration:
   truthful capabilities, `domains` when `net`, `supportsIncremental`
   matching reality, and the envelope-shared display fields
   (`author`/`license`/`repository` provenance, closed-vocabulary
   `categories`, the optional [`docs` pointer](#shipping-your-own-docs-bundle)
   with a validating `docs/docs-tree.json` beside it).
6. Register it (built-in) or ship it as a deployment-image entry point
   (plugin, admin allowlist — an out-of-tree plugin sets
   `manifest_file` to its shipped manifest path). External distribution
   is T2/T3 — see the [recipes](examples-and-use-cases.md).

Test with the vendored conformance kit
(`app/extensions/conformance.py`, `ConnectorConformanceTests`): config
round-trip, idempotency, external_id stability, typed partial errors,
capability honesty and conditional-GET forwarding — all offline.

## Authoring at T2 and T3

- **T3 (external MCP script)**: ship a repo with `manifest.json` whose
  `entry` names your script and whose `mcp: { "transport": "stdio" }`
  declares the external process (the template repo writes
  `"entry": "server.py"` — the filename is a convention, the `entry`
  field is the rule). The script exposes one tool,
  `fetch_postings(config, state) -> {items, next_state}`. Everything you
  return is untrusted and validated
  app-side (required `external_id`/`title`, http(s) URLs, char caps, a
  300-item cap, 64 KB `raw` / 8 KB `next_state` caps). The template repo's
  `server.py` is the complete example —
  [recipe 2](examples-and-use-cases.md#recipe-2--a-t3-mcp-script-connector).
- **T2 (sandboxed module)**: ship `manifest.json` whose `entry` names
  your module (the reference fixture writes `"entry": "extension.py"`)
  with `def fetch(config, state) -> dict`, speaking only the vendored
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
