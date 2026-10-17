# Connector SDK overview

The connector SDK is Career Assistant's one extension point for **posting
sources** — the machinery that moves job data in and out of the app. A
connector is a pure normalizer: it turns an external feed (a job-board API,
an RSS file, a spreadsheet, an MCP script's output) into typed
[`RawPosting`](authoring-and-configuration.md#rawposting--the-only-output-type)
rows, and the app does everything downstream (mapping, fit scoring, feed,
alerts). The SDK is Career Assistant's convergence to the family extension
charter (ADR-0040); the family law lives in the charter and
[`guidelines/extensions.md`](https://neuronection.dev) — kinds, tiers,
capabilities, the typed error model, and the
`{items, next_state, partial_errors}` result envelope.

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

Tier is **provenance at install time**, never manifest data: the artifact
shape decides (`extension.py` ⇒ T2, `server.py` ⇒ T3; both or neither ⇒
rejected). Imported third-party code **never runs in-process** — that is
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

## Where to go next

- Impatient? The [Quickstart](quickstart.md) takes you from clone to
  synced postings in about ten minutes.
- Building a connector? Read [Core Concepts](core-concepts.md), then
  [Authoring & Configuration](authoring-and-configuration.md), then the
  [recipes](examples-and-use-cases.md).
- Operating sources? Start at the user guide:
  [Add a job source](../../user/add-a-job-source.md) and
  [Import extensions from git](../../user/import-extensions-from-git.md).
