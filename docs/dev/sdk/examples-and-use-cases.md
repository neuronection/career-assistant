# Examples & Use Cases

Five recipes, each with the full frame: **when to use**, **when NOT to
use**, **complete code**, **what to be careful at**. Recipes 1–3 are
complete runnable artifacts that this repo's test walls execute (the
code shown is the code under test); recipes 4–5 are operator flows whose
every command appears, with real transcripts, in the
[Quickstart](quickstart.md) and is pinned by
`backend/tests/test_extension_sources.py`.

## Recipe 1 — a T1 builtin connector

*Walks `backend/app/extensions/builtin/job_boards.py`'s Arbeitnow
connector — the file this recipe quotes; wall:
`backend/tests/test_job_board_connectors.py` (conformance + sync +
watermark + filters + robots, against captured fixtures).*

**When to use.** The source is legal-and-free, useful to most
deployments, and worth reviewing and shipping with the product: a public
job-board API with a stable shape. You want the simplest possible
runtime story (in-process, no consent surface, no sandbox) and you own
the maintenance: wire drift (endpoint moves, field renames) becomes a
product fix.

**When NOT to use.** The source needs credentials or per-deployment
negotiation (make it an imported connector with `x-secret` slots); it is
niche or private to one deployment (T2/T3 import); or it requires code
this host should never run in-process (scraping with headless browsers —
T3 script territory). If you are not shipping it in the product image,
you cannot make it T1 — the entry-point path is bundled-only by law.

**Complete code.** The whole connector (verbatim from
`job_boards.py`; the shared watermark/salary helpers it uses live above
it in the same file — `_apply_watermark`, `_stamp_watermark`,
`_sort_and_cap`, `_not_ready`, `_provider_error`, `_protocol_error`,
`_rate_limited`):

```json
{
  "apiVersion": "extension/v1",
  "kindVersion": 1,
  "kind": "connector",
  "id": "career-arbeitnow",
  "version": "1.0.0",
  "description": "Live German/European job board through the public job-board-api (free, no credentials — no secret slots by design).",
  "author": "Neuronection",
  "license": "Apache-2.0",
  "repository": "https://github.com/neuronection/career-assistant",
  "categories": ["search"],
  "docs": "docs/docs-tree.json",
  "capabilities": ["net", "sync"],
  "domains": ["www.arbeitnow.com"],
  "configSchema": {
    "type": "object",
    "properties": {
      "tags": {
        "type": "array",
        "title": "Tag filter",
        "description": "Only keep rows carrying at least one of these tags (empty = all)",
        "maxItems": 16,
        "items": { "type": "string" },
        "default": []
      },
      "max_items": {
        "type": "number",
        "title": "Max items per sync",
        "default": 100,
        "minimum": 1,
        "maximum": 300
      }
    }
  },
  "itemSchema": { "type": "object" },
  "supportsIncremental": true,
  "i18n": {
    "defaultLocale": "en",
    "locales": {
      "en": {
        "title": "Arbeitnow job board",
        "summary": "Live German/European job board through the public job-board-api."
      }
    }
  }
}
```

Abridged — the real file lives at
`backend/app/extensions/builtin/arbeitnow/manifest.json` with its docs
tree in `builtin/arbeitnow/docs/`; `itemSchema` there is the full
postings contract.

Registration is one list entry in `backend/app/extensions/registry.py`
(`_BUILTINS`); the conformance suite subclasses the vendored kit:

```python
class TestArbeitnowConformance(ConnectorConformanceTests):
    connector = ArbeitnowConnector()
    fixture = ...  # the captured wire payload in tests/fixtures/connectors/
```

**What to be careful at.**

- **Politeness is not yours**: never sleep, retry or open sockets in the
  connector — declare `max_requests_per_minute` and let the runtime
  enforce it. Treat a missing `transport` as `not-ready`, never empty
  success.
- **Declared domains must be the truth**: every redirect hop is checked
  against `ARBEITNOW_DOMAINS`. Wire drift that moves a hop off-domain
  surfaces as `net-denied` — that is the guard working, not a bug to
  code around.
- **Honest mapping beats rich mapping**: unmappable employment types
  stay `None`; unparseable salaries stay `None`; malformed rows become
  typed `invalid` partial errors and never persist.
- **Attribution**: boards that ask for credit and link-backs get it —
  the posting URL is the board's URL, so attribution rides the data.

## Recipe 2 — a T3 MCP script connector

*The template repo's `server.py` verbatim — the file itself is the wall
(`test_fixture_copy_matches_the_canonical_template` pins the CI fixture
to it byte-for-byte; `test_template_server_feeds_postings_end_to_end`
runs it through the live pipeline).*

**When to use.** You are an external author, or the source needs logic
the host will never run in-process: a private API with its own SDK,
scraping, transformation, another language entirely. You want
distribution as a plain git repo anyone can audit before consenting.
Your process runs wherever it likes (its own network perimeter —
consent-disclosed) and the host ingests only validated rows.

**When NOT to use.** The source is a plain public JSON API — a T1
builtin (recipe 1) is simpler and politer; or your code is small and
pure — a T2 sandboxed connector (recipe 3) keeps the host's SSRF/robots/
rate guard around your fetches instead of disclosing an open perimeter;
or you need chat tools or surfaces those tiers do not host.

**Complete code.** `manifest.json` is the one shown in
[Authoring & Configuration](authoring-and-configuration.md#the-manifest-reference);
`server.py` in full:

```python
"""The reference career-assistant posting fetcher (T3 script tier).

This server speaks the family fetch contract — one tool:

    fetch_postings(config: dict, state: dict) -> {
        "items": [RawPosting, ...],      # 0..300 rows
        "next_state": {"etag": "..."}    # opaque cursor, round-tripped
    }

Career-assistant calls it as an external MCP server (stdio subprocess
or http endpoint) through its ``mcp`` connector. Everything the tool
returns is UNTRUSTED: the app validates every row against its
RawPosting schema (required external_id/title, http(s) urls, char
caps, a 300-item cap) before persisting anything — malformed rows are
dropped as typed errors, so keep rows honest and small.

The etag pattern below is the whole incremental story: digest the
stable identity of your rows, return it as next_state, and when the
caller hands the same cursor back, return no rows.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta

from fastmcp import FastMCP

mcp = FastMCP("reference-posting-fetcher")


def _rows(board: str) -> list[dict]:
    """Your real fetcher hits an API or scrapes here — the script's own
    network calls are its own business (T3 runs outside the app's
    perimeter; see docs/authoring.md)."""
    return [
        {
            "external_id": f"{board}-1",
            "title": "Backend Engineer (Python)",
            "org": "Reference Systems",
            "url": f"https://jobs.example.com/{board}/1",
            "posted_at": (datetime.now(UTC) - timedelta(days=2)).isoformat(),
            "seniority": "mid",
            "employment_type": "full_time",
            "skills_raw": ["python", "sql", "postgresql"],
            "raw": {"description": "Build ingestion connectors and data pipelines."},
        },
        {
            "external_id": f"{board}-2",
            "title": "Data Platform Engineer",
            "org": "Reference Systems",
            "url": f"https://jobs.example.com/{board}/2",
            "posted_at": (datetime.now(UTC) - timedelta(days=4)).isoformat(),
            "seniority": "senior",
            "skills_raw": ["python", "kubernetes", "docker"],
            "raw": {"description": "Own the platform that ships job data."},
        },
        {
            "external_id": f"{board}-3",
            "title": "QA Automation Engineer",
            "org": "Reference Systems",
            "url": f"https://jobs.example.com/{board}/3",
            "posted_at": (datetime.now(UTC) - timedelta(days=1)).isoformat(),
            "employment_type": "contract",
            "skills_raw": ["python", "testing"],
        },
    ]


@mcp.tool
def fetch_postings(config: dict, state: dict) -> dict:
    """Return the board's RawPosting rows plus an etag cursor.

    config: the per-source config declared in manifest.json
    state:  the last next_state this tool returned (empty on first run)
    """
    board = str(config.get("board") or "default")
    rows = _rows(board)
    digest = json.dumps(
        [[row["external_id"], row["title"], row["url"]] for row in rows], sort_keys=True
    )
    etag = '"' + hashlib.sha256(digest.encode()).hexdigest()[:16] + '"'
    if state.get("etag") == etag:
        return {"items": [], "next_state": {"etag": etag}}
    return {"items": rows, "next_state": {"etag": etag}}


if __name__ == "__main__":
    mcp.run()
```

Import it exactly as the [Quickstart](quickstart.md) does; the admin
configures the minted instance only through the app (transport, tool
allowlist, timeout are validated `mcp` connector config).

**What to be careful at.**

- **The perimeter is yours**: no SSRF guard, robots check or rate limit
  from the app — that is the T3 disclosure your users consent to. Be a
  good citizen yourself; your users' admins can still cap and time you
  host-side (`timeout_seconds` 5–120, one tool per source).
- **Rows are validated and capped**: >300 rows or >8 KB `raw`/
  `next_state` are dropped with typed errors; `url` must be http(s).
  Keep the envelope exactly `{items, next_state}` (+ optional
  `partial_errors` as typed errors).
- **Never put secrets in config**: the config handed to your tool is
  stripped of declared secret slots; tokens arrive only through the
  transport (`token` is an `x-secret` slot resolved host-side).
- **Tier honesty**: your manifest declares `sync` (+`secrets` if you
  need a transport token) — never `net`; your sockets are disclosed,
  not granted.

## Recipe 3 — a T2 sandboxed connector

*The reference fixture `backend/tests/fixtures/t2_reference_extension/`
in full — wall: `test_extension_sandbox.py::test_reference_extension_e2e`
plus the escape matrix in the same file (real child processes).*

**When to use.** You have code (fetch + transform + dedupe state) that
should run behind the host's politeness guard and its quotas, with no
external process to operate: the host mediates your network (scoped to
your declared domains), persists your state, validates your rows, and
kills you if you misbehave. Best fit for small, pure-Python fetchers.

**When NOT to use.** You need sockets of your own, files, subprocesses,
non-stdlib imports (the frozen module surface is closed — see below), or
another language → T3. You need to run outside app uptime → T3. Your
artifact is data, not code → T0 mini-app / plain config.

**Complete code.** `manifest.json` + `extension.py`, the entire
extension:

```json
{
  "apiVersion": "extension/v1",
  "kindVersion": 1,
  "kind": "connector",
  "id": "t2-reference-scorer",
  "version": "1.0.0",
  "description": "Reference T2 connector (plan 32 Phase 5): fetches postings through the host's polite runtime, dedupes against extension-owned state and emits the fresh rows. The code runs sandboxed, not reviewed.",
  "author": "Neuronection",
  "license": "MIT",
  "repository": "https://example.com/neuronection/t2-reference-scorer",
  "categories": ["data"],
  "capabilities": ["sync", "net", "state"],
  "domains": ["example.jobs"],
  "configSchema": {
    "type": "object",
    "properties": {
      "url": {
        "type": "string",
        "title": "Postings URL",
        "description": "The board URL to fetch — must sit under the manifest's declared domains.",
        "maxLength": 500
      }
    },
    "required": ["url"]
  },
  "defaults": {
    "url": "https://example.jobs/postings.json"
  },
  "itemSchema": {
    "type": "object",
    "properties": {
      "external_id": { "type": "string", "title": "External id" },
      "title": { "type": "string", "title": "Title" },
      "url": { "type": "string", "title": "URL" }
    },
    "required": ["external_id", "title"]
  },
  "supportsIncremental": true,
  "i18n": {
    "defaultLocale": "en",
    "locales": {
      "en": {
        "title": "Reference T2 scorer",
        "summary": "A sandboxed postings fetcher with extension-owned dedupe state."
      }
    }
  }
}
```

```python
"""Reference T2 connector (plan 32 Phase 5): fetch postings through the
host's polite runtime, dedupe against extension-owned state and emit the
fresh rows. ~30 lines — the whole authoring story.

The sandbox's entire SDK is the vendored ``capability`` module: net via
``net_fetch`` (host-mediated, scoped to the manifest's declared domains on
every hop), persistence via ``state_get``/``state_set``, results via
``items_emit`` (every row is schema-validated host-side). No sockets, no
files, no environment — the audit wall denies them.
"""

import json

from capability import items_emit, net_fetch, progress, state_get, state_set


def fetch(config, state):
    """One sync tick: ``config`` is the instance config, ``state`` the
    host-round-tripped sync cursor (opaque to us)."""
    response = net_fetch(config["url"], headers={"Accept": "application/json"})
    rows = json.loads(response["body"])
    progress(percent=50, message_key="fetch.fetched")
    seen = set(state_get("seen") or [])
    fresh = [row for row in rows if row["external_id"] not in seen]
    items_emit(fresh)
    state_set("seen", sorted(seen | {row["external_id"] for row in fresh}))
    progress(percent=100, message_key="fetch.done")
    return {"next_state": {"fetched": len(rows)}, "stats": {"fresh": len(fresh)}}
```

Import follows the same pipeline (git source → discovery → consent with
the T2 disclosure verbatim → digest-pinned install → enable → sync);
the minted instance's `connector_key` is the extension id and the
registry routes every sync through the sandbox runner.

**What to be careful at.**

- **The frozen module surface**: only the vendored `capability` module
  plus pure helpers (json, re, math, decimal, statistics, datetime,
  itertools, functools, collections, heapq, bisect, string, textwrap,
  unicodedata, random). An import outside it is denied typed
  (`path-denied` for fs-shaped attempts, `net-denied` for sockets,
  `unsupported` otherwise); `open`/`eval`/`exec` don't exist in your
  namespace.
- **Quotas are real**: wall-clock watchdog per call, memory cap
  (POSIX), call rate, calls per run, net+items+state bytes per day,
  progress/log events per run — exhaustion is a typed `budget` error
  and the run ends cleanly. See the knobs table in
  [Reference](reference.md#sandbox-knobs).
- **Death semantics**: a crash or watchdog kill self-disables the
  install (surfaced reason on the instance); an explicit re-enable is
  the only way back. Protocol garbage recycles the child (typed
  `protocol`) without disabling.
- **Secrets never cross the seam**: `cap.secrets.need` returns STATUS;
  the host substitutes `{{secret:<slot>}}` placeholders into your next
  fetch's **headers** host-side — a placeholder in a URL is refused
  typed `invalid` (URLs leak via logs, redirects, Referer and error
  paths). There is no message shape that can carry a value: the
  response's `finalUrl` and every error detail cross back scrubbed.
- **Frozen builds**: a PyInstaller-frozen host has no interpreter to
  spawn — T2 installs self-disable typed `unsupported` there
  (capability detection, never a hard dependency; probe with
  `careerassistant enginecheck`).

## Recipe 4 — git-source distribution, updates and re-consent

*Operator flow; wall: `test_extension_sources.py` (the update engine,
drift and re-consent cases). Transcript of the import half: the
[Quickstart](quickstart.md).*

**When to use.** You distribute a connector (or mini-app) as a repo and
want installs to be pinned, auditable and explicitly updated — the
template repo's distribution model. Also the admin path for adopting
any external extension.

**When NOT to use.** For throwaway local experiments the dev-only
`local` source variant exists but is gated (allowlisted roots,
non-production boots) — do not build a workflow on it. For first-party
engines shipped with the app, bundling (recipe 1) needs no source
management at all. Do not use a mutable branch ref as a pin when you
mean a release — prefer `tag-pattern`.

**The complete flow** (CLI form; the Settings → Tools → Connectors UI
rides the same lifecycle):

```bash
cd backend
uv run python -m app.extensions.cli source add descriptor.json    # https git URL (prod) or gated local path
uv run python -m app.extensions.cli source sync <origin-or-id>    # discover + validate + update-check
uv run python -m app.extensions.cli source install <origin> <extension-id> --consent
# ... later, after the source moved:
uv run python -m app.extensions.cli source sync <origin-or-id>    # records state: available + manifestDiff
uv run python -m app.extensions.cli source pin <extension-id> --consent   # the ONLY apply path
uv run python -m app.extensions.cli source remove <origin-or-id>  # installs park, data intact
uv run python -m app.extensions.cli source validate <path-or-url> --ref branch=main
```

`source validate` is the authoring helper — descriptor + manifest +
host-profile checks read-only, so a repo owner verifies their extension
imports cleanly before sharing the git URL.

What the update engine does, exactly:

- identical digest at a moved ref ⇒ the pin moves (nothing consented
  changed);
- changed digest ⇒ the update is *offered* (`state: available`,
  `requiresReconsent: true`, manifest diff recorded) — `source pin
  --consent` (or the apply API) is the only apply path;
- digest change under the **same pinned ref** ⇒ `digest-drift`: loud
  failure, source degraded, pins untouched — verify the source and
  re-consent explicitly;
- capability growth or `configSchema` change always re-consents
  (browser-permission model); T0 data diffs auto-apply only on a
  byte-identical manifest.

**What to be careful at.**

- **Never auto-apply**: no path applies imported code without an
  explicit consent call — do not script `pin --consent` unattended.
- **Credentials are sealed slot references** (private repos): supply
  them through the admin API/settings UI; an inline token is
  structurally invalid at the schema seam.
- **Removal parks, never deletes**: content, consent and pin history
  survive source removal and tombstones — re-import revives history
  instead of silently re-enabling.

## Recipe 5 — a GitOps admin fleet

*Operator flow; wall: `test_extension_sources.py` (the GitOps conflict
cases) and the hourly `extension_reconcile` scheduler trigger.*

**When to use.** You operate several Career Assistant instances (a
school, a program) and want one reviewed document to define which
extension versions each fleet runs — pin moves land everywhere on the
next reconcile without per-instance clicking.

**When NOT to use.** For a single instance, manual sources (recipe 4)
are simpler. GitOps is **not** an enforcement or auto-enable mechanism —
it never enables code and never deletes data; if you want something
installed everywhere you still consent per instance once. And the model
never authors this document (ADR-0011 §7) — it is admin data.

**The complete flow.** Write the desired-state document (validated
against the vendored `desiredStateDocument` schema — `schema: 1`,
`sources[]` descriptors, `extensions[]` entries naming id + sourceUrl +
pin; the `enabled` field exists but reconcile deliberately ignores it),
put it, reconcile:

```bash
cd backend
cat > desired.json <<'JSON'
{
  "schema": 1,
  "sources": [
    {"url": "https://github.com/your-org/career-connector-template.git",
     "ref": {"strategy": "tag-pattern", "value": "v*"}}
  ],
  "extensions": [
    {"id": "example-posting-fetcher",
     "sourceUrl": "https://github.com/your-org/career-connector-template.git",
     "pin": {"ref": "v1.0.0", "digest": "a9d112f30ca4d43c6266794b8b4ebe78c50692750c38392cce67df05096f21c8"}}
  ]
}
JSON
uv run python -m app.extensions.cli desired-state put desired.json
uv run python -m app.extensions.cli reconcile
```

Reconcile runs at boot, hourly (`system_extension_reconcile`), and on
demand, and it: moves pins only for the extensions the list names
(manual installs are reported as drift, never touched); never
auto-enables (`ignoredEnableIntent` in the report); never deletes data
(deletion is structurally inexpressible — removal from the list parks
gitops-managed installs disabled + tombstone-able); installs an entry
only when a consent record already exists at that exact digest —
otherwise `needsConsent`; leaves pins untouched on a failed fetch and
marks the source `failing`. The report keys:
`installed`, `pinsMoved`, `needsConsent`, `updatesAvailable`, `drift`,
`parked`, `failures`, `ignoredEnableIntent`.

**What to be careful at.**

- **The list is a pin-mover, not a consent bypass** — bootstrap each
  new digest once per instance through the consent surface (recipe 4).
- **Pin by digest**: a `pin.digest` mismatch against the source is
  reported drift, not coerced; that is your supply-chain tripwire.
- **Private fleet repos** use the same sealed credential slots as any
  source.
