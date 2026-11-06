# Connector SDK overview

The connector SDK is Career Assistant's one extension point for **posting
sources** — the machinery that moves job data in and out of the app. A
connector is a pure normalizer: it turns an external feed (a job-board API,
an RSS file, a spreadsheet, an MCP script's output) into typed
[`RawPosting`](authoring-and-configuration.md#rawposting--the-only-output-type)
rows, and the app does everything downstream (mapping, fit scoring, feed,
alerts). The SDK is Career Assistant's convergence to the family extension
charter (**ADR-0040**): kinds, tiers, capabilities, the typed error
model, the limits, and the
`{items, next_state, partial_errors}` result envelope. The charter's
authoritative data is vendored into this repo at
`contracts/extension-charter.json` +
`contracts/extension-manifest.schema.json`, and this set describes that
law as it applies to this host. ADR and plan numbers cite
family-governance documents that live in the Neuronection dev repo and
are not shipped here — when this prose and the vendored contracts
disagree, the contracts win and the prose is the bug.

The mental model in three sentences:

- **Connectors are data adapters, never plugins.** They emit validated
  rows through an injected transport; they never touch the database, the
  AI layer, or sockets of their own.
- **Trust is a ladder, decided by where code runs.** Bundled code runs
  in-process (T1); imported code runs either sandboxed behind a capability
  RPC (T2) or as an external process (T3) — never in-process.
- **Every import is consented and pinned.** Content lands
  content-addressed by digest; updates re-consent; nothing auto-applies.

## The tier ladder

| Tier | Name | Where the code runs | Precedents |
|---|---|---|---|
| T0 | declarative | Validated data only; the host interprets; no code ever | mini-app packs (`cv-gallery`), CSV/JSON-LD sources |
| T1 | bundled | Reviewed code shipped inside the product, in-process | the builtin engines, the three real job boards |
| T2 | imported code | Third-party code in a subprocess behind the capability-RPC sandbox | the reference `t2-reference-scorer` |
| T3 | external process | A separate MCP server the app calls; its sockets are its own | the `mcp` script tier, `career-connector-template` |

Tier is **provenance at install time**, never a caller claim: the
manifest's `entry` field decides (`entry` + `mcp` ⇒ T3, `entry` ⇒ T2,
no `entry` ⇒ T0 declarative; bundled ⇒ T1), cross-checked against the
bundle it describes. The `extension.py` /
`server.py` filenames are the template repo's convention, not a rule.
Imported third-party code **never runs in-process** — that is
the charter's load-bearing rule, and it is why the entry-point plugin path
is T1-bundled-only.

## When an extension vs a builtin feature

**Write a connector/extension when** the thing you want is a *data source
or surface that varies per deployment*: another job board, a university
feed, a private ATS, a CV-utility mini-app. Extensions ship out-of-band,
install per instance with consent, and update by re-consent — no app
release needed.

**Write a builtin feature when** the capability must be reviewed with the
product (any auth-adjacent or AI-adjacent behavior), when it needs
in-process performance or direct service access, or when every deployment
should have it. Builtins land under
[`backend/app/extensions/builtin/`](installation-and-modes.md#bundled-vs-imported)
with a validated manifest and registry entry — same SDK, reviewed and
shipped in the image.

**Never** an in-process plugin from outside: there is no such path. The
entry-point group `career_assistant.connectors` is admin-allowlisted and
reserved for code shipped in the deployment image; external authors write
T3 MCP connectors or T2 sandboxed connectors.

## What this set does not cover

Host machinery that sits beside the extension point — no manifest ever
declares it, so it is not authoring surface:

- **Web-search providers** (`app/extensions/search_providers.py`,
  `search_adapters.py`) — provider choice and keys are in-app
  configuration, not extension code.
- **The AI-layer MCP client bridge** (`app/extensions/mcp_bridge.py`) —
  the app as an MCP *client* feeding model tools; distinct from the T3
  `mcp` connector this set documents (the app as host of *your*
  fetcher).
- **GitHub intake** (`app/extensions/intake.py`) — bundled content
  intake with its own registry; not importable, not configurable.
- **Market-data providers** (`app/extensions/market_data.py`) — a
  sibling extension registry: its own entry-point group
  (`career_assistant.market_data`), its own admin allowlist
  (`CAREER_MARKET_DATA_PLUGINS_ALLOWLIST`), bundled-code-only. The
  bundles do carry `extension/v1` manifests validated against the
  vendored envelope — but the item contract is `ObservationCreate`
  (series/observations, not postings) and the provider protocol,
  license-class gating and ingest seam are their own. Not the
  connector SDK's `fetch`/`RawPosting` contract.
- **The posting pipeline** (catalog mapping, AI extraction, fit
  scoring, feed) — you emit `RawPosting` rows and core does the rest.
  See the user guide
  [Postings and search](../../user/postings-and-search.md).

If you need one of these to become extensible, that is a family charter
question — a new `kind` or capability — and starts there, never as a
manifest field invented on one host.

## Where to go next

- Impatient? The [Quickstart](quickstart.md) takes you from clone to
  synced postings in about ten minutes.
- Building a connector? Read [Core Concepts](core-concepts.md), then
  [Authoring & Configuration](authoring-and-configuration.md), then the
  [recipes](examples-and-use-cases.md).
- Operating sources? Start at the user guide:
  [Add a job source](../../user/add-a-job-source.md) and
  [Import extensions from git](../../user/import-extensions-from-git.md).
