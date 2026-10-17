# Quickstart — import the connector template and fetch postings

One path, about ten minutes: clone the reference connector repo, import it
as a local source, consent, enable, sync — and real postings land. Every
command below was executed against a clean scratch environment; the
transcripts are the actual output (fastmcp's startup banner on the spawned
server's stderr trimmed). The same pipeline runs in CI as
`backend/tests/test_extension_sources.py::test_e2e_import_from_a_local_git_repo`
and `backend/tests/test_mcp_connector.py::test_template_server_feeds_postings_end_to_end`.

**Prerequisites**

- The Career Assistant backend checkout with its environment
  (`uv sync`) — you run from `backend/`.
- `git` on PATH (sources are git repos, even local ones).
- A scratch directory for this walkthrough (here `$CA`):
  `export CA=/tmp/ca-sdk-quickstart && mkdir -p "$CA"`.
- The sibling template repo to clone from — any checkout of
  [career-connector-template](https://github.com/neuronection/career-connector-template)
  will do; below we clone the family sibling.

## 1. Clone the template repo

```bash
git clone /path/to/career-connector-template "$CA/career-connector-template"
```

The repo's default branch is `master`; its root carries the reference T3
fetcher (`server.py` + `manifest.json`, id `example-posting-fetcher`), the
`cv-gallery/` mini-app, and the `connectors/` adoption manifests.

## 2. Point the app at a scratch SQLite profile

The CLI rides the app's own settings; these environment variables give it
a throwaway database and data dir, allow the local source root, and opt
the admin in to the script tier (the `mcp` connector is off by default):

```bash
export CAREER_APP_ENV=development
export CAREER_DATABASE_URL="sqlite+aiosqlite:///$CA/career.db"
export CAREER_DATA_DIR="$CA/data"
export CAREER_EXTENSION_LOCAL_SOURCE_ROOTS='["'$CA'"]'
export CAREER_CONNECTOR_PLUGINS_ALLOWLIST='["mcp"]'
cd backend
uv run alembic upgrade head
```

The last lines of the migration run:

```
INFO  [alembic.runtime.migration] Running upgrade 0048 -> 0049, Plan 32 Phase 5 / ADR-0030 (Python port): the T2 sandbox runner's store.
INFO  [alembic.runtime.migration] Running upgrade 0049 -> 0050, Plan 32 follow-up (D20 / ADR-0011 / ADR-0015): the destructive-confirm runtime funnel's store.
```

(List-valued settings parse JSON from the environment — hence the
quoted `["…"]` forms. Local sources are dev/test-only: production boots
reject them `path-denied`, and even in development they must sit under an
allowlisted root.)

## 3. Add the source, sync it, consent-install the extension

```bash
cat > "$CA/source.json" <<JSON
{
  "local": {"path": "$CA/career-connector-template"},
  "ref": {"strategy": "branch", "value": "master"}
}
JSON
uv run python -m app.extensions.cli source add "$CA/source.json"
uv run python -m app.extensions.cli source sync "$CA/career-connector-template"
```

`source sync` fetches, discovers manifests (the repo root plus one level
of child directories), validates them against the vendored envelope
schema and checks this host's profile. It reports one line per candidate:

```
candidate: example-posting-fetcher | compatible: True | hasEntry: True | digest: a9d112f30ca4… | subpath: .
candidate: career-cv-gallery | compatible: True | hasEntry: False | digest: d37107885096… | subpath: cv-gallery
```

`example-posting-fetcher` is the T3 fetcher (a `server.py` beside the
manifest ⇒ tier T3). Install it — the `--consent` flag records your
consent to exactly the digest shown:

```bash
uv run python -m app.extensions.cli source install "$CA/career-connector-template" example-posting-fetcher --consent
```

```json
{
  "id": "87f22673-2cf0-4939-b8cb-161d39caeee6",
  "extensionId": "example-posting-fetcher",
  "version": "1.0.0",
  "digest": "a9d112f30ca4d43c6266794b8b4ebe78c50692750c38392cce67df05096f21c8",
  "pinRef": "f509ffe96f1a11e90ca001998e8cc4b98cd4537d",
  "tier": "T3",
  "originClass": "imported",
  "state": "installed",
  "enabled": false,
  "sourceKey": "example-posting-fetcher",
  "contentPath": "/tmp/ca-sdk-quickstart/data/extensions/example-posting-fetcher/a9d112f30ca4d43c6266794b8b4ebe78c50692750c38392cce67df05096f21c8",
  "provenance": { "author": "Neuronection", "license": "MIT", "...": "..." }
}
```

Three things happened: the content landed content-addressed under
`data_dir/extensions/<id>/<digest>/`, a **disabled** `mcp` job source was
minted whose stdio command spawns the cloned `server.py`, and your
consent record (who/when/what-digest + the T3 disclosure verbatim) was
stored on the install. Enabling is a separate explicit act — nothing
auto-enables.

## 4. Enable the instance and sync postings

In the running app: **Settings → Tools → Connectors → Extension sources
(git import)**, enable the `example-posting-fetcher` import, then sync
it like any job source. (Enable and job-source sync are admin UI/API
acts — the CLI intentionally has no enable command; the API routes are
`POST /api/v1/admin/extensions/installs/{id}/enabled`
and the postings sync.) The first sync spawns the server from the
cloned content and persists its rows; the etag cursor it returns makes
the second sync a no-op. Real output from this walkthrough (via the
same service calls the admin API rides):

```
first sync:  {'synced': 3, 'extract_queued': 3, 'errors': []}
second sync: {'synced': 0, 'extract_queued': 0, 'errors': []}
postings persisted: 3
```

**Success criterion:** three postings on the Postings page — *Backend
Engineer (Python)*, *Data Platform Engineer*, *QA Automation Engineer*,
all from *Reference Systems* with `jobs.example.com` URLs — and the
source's sync state carries the tool's etag cursor. One audit row lands
on the AI audit funnel per tool call (`mcp_tool_call`).

## Where next

- [Core Concepts](core-concepts.md) for the nouns you just used, then
  [Authoring & Configuration](authoring-and-configuration.md) to replace
  the template's `_rows()` with your real source.
- The [T3 recipe](examples-and-use-cases.md#recipe-2--a-t3-mcp-script-connector)
  walks the same server's code; the
  [git-distribution recipe](examples-and-use-cases.md#recipe-4--git-source-distribution-updates-and-re-consent)
  covers updates and re-consent.
- To clean up: remove the scratch directory and drop the scratch DB file.
