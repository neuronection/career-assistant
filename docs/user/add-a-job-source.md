# Add a job source

Career Assistant pulls live job postings into your workspace through
**job source connectors**. Three real job boards work with zero
configuration — no account, no API key — and four more engines cover
feeds, spreadsheets and single URLs. Sources live in
**Settings → Tools → Connectors** (an admin surface).

## The zero-config job boards

Add a source, sync, done — each board is a free public API with polite
request budgets built in, and every posting carries a link back to the
original listing (the boards' terms ask for exactly that credit).

| Board | What you get |
|---|---|
| **Arbeitnow** | Live German/European board — rotates fresh listings hourly |
| **Remotive** | Remote jobs across software, product, design and more |
| **Jobicy** | Remote jobs, API v2 — structured salaries and levels |

To enable one: **Settings → Tools → Connectors → Job source
connectors → Add**, pick the board, leave the defaults (optional
filters: a tag or category focus, a per-sync item cap) and save. Then
**Sync now** — postings appear on the Postings page and flow into
Explore, saved-search alerts and your match scores.

**The Remotive robots caveat, honestly.** Remotive's site-level
`robots.txt` disallows its API path, and Career Assistant respects
robots policies by default — so Remotive syncs can surface a clear,
typed *network denied* error instead of fetching silently. Remotive's
own API terms welcome API consumers; if you run the instance and agree,
an admin can lift the check for that deployment (the
`CAREER_CONNECTOR_RESPECT_ROBOTS` setting). It is deliberately an
admin's explicit decision, never a quiet bypass baked into the app.

## The other bundled engines

| Engine | What it reads | Needs |
|---|---|---|
| **ATS API** | Public applicant-tracking-system job APIs (Greenhouse / Lever / Ashby) | the company's board slug; a token only for protected boards |
| **JSON-LD** | `schema.org/JobPosting` structured data on any page you point at | a URL |
| **RSS** | Job feeds | a feed URL |
| **CSV** | Exported spreadsheets of postings | an upload |
| **Paste-a-URL** | A single posting you point at | a URL |

Credentials, where a board needs them, are stored encrypted and only
unsealed at sync time — you'll see a slot with a last-4 hint, never the
value echoed back.

## After the first sync

- Postings map onto the catalog by literal skill-ID intersection and
  inherit your fit score (see
  [Postings and search](postings-and-search.md)).
- Sources sync on the scheduler's cadence, or on demand with
  **Sync now**.
- Each source row shows its status — healthy, degraded or failing —
  with the last success time.

## Related

- [Import extensions from git](import-extensions-from-git.md) — add
  connectors that aren't bundled with the app
- [Extension troubleshooting](extension-troubleshooting.md) — decode
  sync errors
- [Postings and search](postings-and-search.md) — what happens to
  postings after they land
