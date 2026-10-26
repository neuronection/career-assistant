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

## The DACH board pack

The German-speaking market is covered by employer career-site feeds and
board alerts. All of these read public data; the only personal value is a
StepStone/Xing alert URL, which is stored in a sealed secret slot.

| Source | What it reads | Needs |
|---|---|---|
| **Personio** | A Personio career site's public XML feed (`<tenant>.jobs.personio.de/xml`) | the tenant (the subdomain before `jobs.personio.de`) |
| **JOIN.com** | JOIN's public company job API | the numeric company id and the public slug |
| **Recruitee** | A Recruitee career site's public `/api/offers/` feed | the company subdomain |
| **Teamtailor** | A Teamtailor career site's public JSON Feed | the company subdomain |
| **StepStone / Xing** | Your signed-in job-alert RSS feed | the personal alert URL (sealed slot) |

Personio, JOIN, Recruitee and Teamtailor carry no credentials; the
StepStone/Xing alert URL often embeds a per-user token, so it is declared
as an `x-secret` slot and never written into stored config.

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

## Follow my radar (search source)

The source form's **Search source** switch decides where the search
comes from:

- **Static config** — the source's own settings (keywords etc. in its
  Tool options) drive every sync.
- **Follow my job radar** — keywords and location come from the
  [job radar](job-radar.md) instead. Each sync searches one focused
  role group and rotates through them, so a wide radar never means more
  traffic. The form shows the current query and rotation position
  (e.g. *Searching 2/3: devops @ Berlin, Germany*). The switch only
  appears on connectors that support dynamic queries.
- **Queries per sync** (1–3, shown in radar mode) — how many rotating
  groups one sync searches. **1 is the ban-safe default**; each extra
  query runs strictly sequentially with a jittered pause in between
  (never in parallel), and the whole run stays inside the source's time
  budget. Between syncs the app's regular source schedule paces things
  further — batching never means hammering.

MCP-script sources also have a **Tool options** field (JSON object) for
tool-level settings — the place keywords/location live in static mode —
so nothing needs to hide in the command line.

## After the first sync

- Postings map onto the catalog by literal skill-ID intersection and
  inherit your fit score (see
  [Postings and search](postings-and-search.md)).
- Sources sync on the scheduler's cadence, or on demand with
  **Sync now**.
- Each source row shows its status — healthy, degraded or failing —
  with the last success time. **Pause syncing** stops the scheduled runs
  without deleting the source; **Resume syncing** restarts them.

## Bring in a GitHub profile

**Profile → Import** also has a **GitHub** card: enter a public GitHub
login, preview its non-fork repositories, tick the ones worth keeping and
choose **Create drafts**. Each repository becomes a draft project (with an
achievement highlight when it has stars or forks) that you review and
activate in your profile — nothing is ever written as active, and a
repository already on your profile is skipped.

## Related

- [Import extensions from git](import-extensions-from-git.md) — add
  connectors that aren't bundled with the app
- [Extension troubleshooting](extension-troubleshooting.md) — decode
  sync errors
- [Postings and search](postings-and-search.md) — what happens to
  postings after they land
