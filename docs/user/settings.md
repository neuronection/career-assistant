# Settings reference

Settings live under `/settings`, grouped in a two-pane shell with a section
rail. This page explains each page and its purpose.

## Account (`/settings/account`)

Account self-service — every signed-in user, on any instance mode:

- **Profile** — your name, email and admin badge, plus the profiles your
  data is scoped to: create additional profiles, choose which one is
  the default, and delete ones you no longer need (deleting a profile
  deletes everything scoped to it). Switching the active profile stays
  in the top bar.
- **Appearance** — pick the interface language (English, German or Greek).
  The choice is personal and applies immediately, including the catalog
  labels that have an approved translation. Admins also set the
  **instance default** used by people who have not chosen one.

- **Signed-in devices** — every login opens one session per device
  (shown by its device label). Sign out anything you don't recognize;
  the device you are using is marked, and signing it out returns you to
  the login screen. **Sign out everywhere** revokes every session at
  once (this one included).
- **Password** — current password plus a new one (10+ chars). You stay
  signed in; every other device is signed out.
- **Data & privacy** — request a full export of your profile,
  applications, documents and settings as a downloadable archive.
- **Delete account** — a danger-zone card: enter your password to arm
  the button, then confirm. Everything you own (profiles, applications,
  documents) is deleted with it. This cannot be undone.

## AI Configuration (`/settings/ai`)

The one place AI is configured. There are deliberately **no AI environment
variables**. On a fresh install the app leads you here through the
[first-run setup wizard](ai-setup.md) instead of failing silently.

- **Providers** — add an OpenAI-compatible provider (OpenAI, OpenRouter, or a
  local Ollama/LM Studio via a base URL). API keys are encrypted at rest and
  masked in every response; a masked `***` on update means "keep existing".
- **Models** — register the models a provider offers, with their capabilities
  (text, vision, tools, embeddings, audio).
- **Tasks** — assign a model to each AI task (matching, generation, parsing,
  chat, CV drafting, posting extraction, interview coaching, and so on).
  Assignments can differ per task, so you can use a cheap model for one job
  and a strong model for another.
- **Connection test** — verify a provider before relying on it.

A fresh production install starts unconfigured; AI endpoints answer `503`
until an admin adds a provider.

## Tools (`/settings/tools`)

Admin-only, four URL-addressable sections. **Web search** ships
SearXNG plus five keyed providers — Tavily, Brave, Exa, Serper and
Google Programmable Search;
the first enabled provider that answers wins. Each provider renders as a
card with its priority badge and connection status; the card's **⋯ menu**
carries enable/disable, reorder, test, edit and delete, and **Add
provider** opens a choose-then-configure wizard. See
[Add a job source](add-a-job-source.md) and
[Import extensions from git](import-extensions-from-git.md).

**MCP** hosts the MCP server surface as section cards: the endpoint
URL with the write-access switch, the token lifecycle (mint shown
once, rotate, revoke), copy-ready client setup snippets, the live tool
catalog collapsed behind a searchable disclosure, the recent-call
audit and the chat-tools GitHub credential. While the write switch is
off, MCP clients see read tools only. See
[MCP access](assistant-chat.md#mcp-access).

**Retrieval** is the vector-index operations surface at
[`/settings/tools?section=retrieval`](/settings/tools?section=retrieval).
The active-space card
shows the honest backend label (PostgreSQL pgvector/HNSW, SQLite sqlite-vec,
or the desktop-scale linear fallback), model and dimension, store health,
coverage and the coverage/quality gates. **Coverage & reindex** queues a
bounded run by kind, view and since timestamp with a token budget and
document limit, then shows the queued run and its status — a queued run is
not a finished reindex. The **Tokenizer & limits** card names the
tokenizer/source, says whether the count is exact or approximate, shows the
model input limit and the current character-chunk budget, and measures the
English/Greek/German/CJK/code char-vs-token spread plus a bounded corpus
sample. Its **model profile** block shows the auto-resolved profile
(curated, admin override or the visibly labelled fallback), the per-request
batch item/token limits and the default token chunk budget; an admin can
save a bounded tokenizer/limit override for a provider-class + model pair, or
reset it to the curated profile. Curated open-source profiles show their
family, license and source link, and an unavailable preset (for example a
gated repository) is labelled instead of being presented as supported. For a
Hugging Face tokenizer the editor takes the repository, a full 40-character
commit revision and the `tokenizer.json` checksum; **Fetch tokenizer** queues
a bounded, audited admin job (never a page-load download), shows its progress
and fills the verified checksum so the profile can be saved. A missing or
corrupt cached asset stays visibly approximate until it is fetched. The
build-space form previews the same profile for the provider/model being
entered, so a fallback is visible before the space exists. Profile changes
are settings only: no existing chunk, token column, record or space is
rewritten. A profile change therefore applies to **future** spaces; an
existing space is not re-chunked in place.
**Spaces** lists active, building and retired
spaces; changing models means building a new space (never an in-place
rewrite), activating it only after coverage and the golden-query compare
pass, then retiring the old one. **Build new space** defaults to a
**token-aware (v2)** build: it shows the resolved tokenizer with its source,
exact/approximate flag, pinned revision, checksum and model input limit, warns
when the conservative fallback applies, and lets you edit the chunk token
budget, overlap and character ceiling within safe bounds. The build pins that
tokenizer and chunk budget in the new space's identity. Switching token
awareness off deliberately creates a legacy v1 space with character chunks.
The space card, Audit space drawer and Audit run drawer show the real chunker
and link the operator runbook. The old space stays retained until you
explicitly retire and drop it; nothing is re-chunked in place. **Index maintenance** queues an index
rebuild, vacuum, orphan sweep or failed-document retry, with a dry run where
supported. **Quality** scores the versioned golden-query set for a candidate
against its baseline and shows recall, precision and the gate. The **danger
zone** exports the status JSON (aggregates, counts, ids and scores only —
never document, query or prompt text) and offers typed-confirmation deletion
of retired spaces. Observation lives in
[Audit → Retrieval](/settings/audit?tab=retrieval&section=overview): a
read-only tab with overview, spaces, runs, quality, query-health, failures,
usage and changes sections, each deep-linkable and every action handing off
to this Tools surface. A space that has never been reconciled says “never
reconciled”, and ANN recall says “not sampled” until the probe runs; a
degraded query reports its lexical-fallback reason instead of pretending the
index served it.

**Retrieval debug marker** is the last card before the danger zone: one
switch that draws a small semantic-index state dot on the `/postings` cards
of this browser, so an operator can see at a glance which postings the index
has actually reached. The flag is stored per browser (never on the server),
and the card shows the current space while it is on. The dot means
**Indexed** (current), **Indexed · text changed since** (stale),
**Not indexed** (missing), **Index incomplete** (incomplete) or **Semantic
index is off** (no active space); clearing the cached statuses forgets what
this browser has already fetched. It is a diagnostic only — no card, badge
or ranking changes for a normal user.

**Sources** hosts the job-source instances: grouped by what they feed —
**Job boards**, **Market data**, **Universities**, **Search** and
**Inbound webhooks** — with a health strip (active count, failing /
degraded badges, last sync) over the rows. Each row shows a health badge
(healthy / degraded / failing) with its last successful run and one
**slider toggle** — the row's name is the toggle's label, so clicking the
name pauses or resumes the source (off parks the schedule without
deleting the configuration). **Test** runs a typed probe inline; **Sync
now, Docs, Query plan, Manage and Remove** live in the row's **⋯ menu**.
**Add source** opens a two-step wizard: pick the connector from catalog
tiles, then configure it — secret slots are sealed at rest and never
echoed back. Market-data sources feed the demand import (salary and
outlook provenance on catalog jobs) rather than the posting feed, so they
run on the daily demand schedule. Extension sources (git import) render
as their own card — **Install from Git** — digest-pinned and
consent-gated.



## Taxonomy (`/settings/taxonomy`)

Curate the interest tags and the skills ontology (categories, level anchors,
aliases, lifecycle). The catalog, profiles and AI outputs all reference the
taxonomy by stable `key` slugs, so changes here are what keep labels and
translations from breaking data. Unknown skills introduced by users or the AI
appear as `proposed` rows for review.

The page opens with a **work-queue bar** over everything you own: the skill
ontology by lifecycle state (active, proposed, deprecated, and how many the
corroboration gate promoted — all time and in the last seven days), then
every review queue's live count (relations, enrichment, draft paths,
translations). The counts come from the server, so a tab badge and a tile
never disagree; a queue's tab carries its count until the queue is empty.

Tabs and subtabs are URL-addressable: add `?tab=` (interests, skills,
paths, enrichment, translations, relations) and, for the Relations
subtabs, `&section=` (queue, editor, graph, thresholds, runs) —
refreshing or sharing a link reopens the exact view.

The **Relations** tab curates the typed edges between skills ("java is a
programming language"): a review queue for the discovery job's suggestions
(accept, dismiss or save a raw label as an alias), a manual editor for
existing relations, the discovery thresholds and each run's statistics.
See [Skill taxonomy & relations](skills-taxonomy.md).

The **Translations** tab drafts translations for jobs, skills and job
families with the configured AI. Drafts never render: review each one
against the base label, edit the wording if needed, then approve or
reject — one card at a time or a whole batch. Approval is the only route
to the catalog, search, rankings, chat and CV surfaces. University names
stay authoritative (an overlay may translate the display label, never
rewrite the stored name).

## Companies rules (`/settings/companies`)

Admin review surface for how employer names resolve to companies
(plan 135). Every learned decision is editable here. Tabs are
URL-addressable via `?tab=` (suggestions, aliases, exclusions, queue,
thresholds) — refreshing or sharing a link reopens the exact view.

- **Merge suggestions** — near-miss pairs the matcher was unsure about.
  Accepting merges the label's company into the established one
  (postings re-point, aliases fold); dismissing records a never-link
  exclusion so the same near-miss never resurfaces.
- **Aliases** — pick a company and manage its known name variants
  (P&G, Procter & Gamble, P&G GmbH …): add, remove, exclude (kept as
  negative history, never matched) or reactivate.
- **Exclusions** — global "not a company" labels (the seeded denylist:
  "Confidential", staffing agencies …) and per-company never-link
  pairs. Adding one here removes the label from matching everywhere.
- **Pending pairs** — the gray-band queue awaiting AI arbitration
  (empty unless a provider is configured).
- **Thresholds** — the auto-link score, the gray-band lower bound and
  the AI auto-accept confidence. Without a configured AI provider the
  queue degrades to suggestions rather than stalling ingest.

## Users (`/settings/users`)

Manage users (admin-only): the account list with activity counts,
activate/deactivate, promote/demote, password reset (the new password is
shared out of band) and forced sign-out. Guard rails hold: you cannot
change your own role or status, and the last admin cannot be demoted or
disabled. The web deployment registers its first user as the instance
admin; the desktop app runs single-owner (DIM) with no user management
needed. Whether self-service registration is open is a deployment
switch — see
[Privacy and security](privacy-and-security.md#authentication).

## Automations (`/settings/automations`)

Configure the one periodic engine: saved-search schedules (interval, daily,
weekly or cron), the digest and check-in rhythm, source syncs and re-fit
sweeps, each with its next run, last outcome and failure count. Your own
runs (check-ins, digests, radar scans) can be paused or triggered from the
row — **Scan now / run now** makes them due immediately, the row switch
pauses without deleting. Admins also see the instance-wide system
schedules with run-now and pause; their failures alert the admins
automatically. The legacy scheduler deep link redirects here. See
[Notifications and scheduler](notifications-and-scheduler.md).

## Notifications (`/settings/notifications`)

Configure the notification funnel: channel cards (email with double opt-in,
webhook, browser push, desktop toasts) with a delivery-health strip, quiet
hours, per-kind × per-channel routing (grouped matrix with instant switches,
reset-to-default per kind), alert rules (fit threshold, family targeting,
per-day caps), calendar/RSS tokens, follow-up cadence and the admin zone
(instance SMTP transport + announcements to every active user). Email
addresses need a one-time confirmation; webhook URLs are validated before
they are saved. See
[Notifications and scheduler](notifications-and-scheduler.md).

## Audit & monitoring (`/settings/audit`)

The observability surface for administrators — on desktop the owner is
their instance's admin, so the page is always reachable there. Eight
tabs over the system's audit streams; the overview, security and
failures views share a 24h/7d/30d or custom range:

- **Overview** — the health snapshot: AI calls (with the change vs the
  previous window), error rate, token usage, average latency, failed
  background jobs and failing schedules, denied sign-ins; a
  call-volume-and-errors chart; calls grouped by category; and the most
  recent failures across AI, jobs and auth in one feed.
- **AI activity** — the full ledger of every AI call. Filters are
  facet-driven from live data (task, provider, status, tier, window,
  free-text search over prompt/error) with pagination; a row opens a
  detail drawer (deep-linkable via ?detail=<id>) with parsed and raw
  views — prompt, validated output, exact tokens, latency and lineage
  (run, stage, prompt version, governing skill pack) — plus prev/next
  stepping through the loaded page. Rows generated by the dev-only mock
  provider are marked as simulated.
- **Security & access** — the identity audit trail: sign-ins, denied
  attempts, refresh-reuse detections, admin actions and instance-mode
  transitions, filterable by group, outcome and actor.
- **Usage & throughput** — per-model AI usage (calls, tokens in/out,
  average latency, errors per provider/model), a token-usage trend
  chart, and production throughput: postings ingested (with processing
  activity by actor), skill lifecycle events, company profiles created
  and catalog jobs created — split by status and origin (seed/AI/user),
  tying content production back to the AI ledger.
- **Jobs & runs** — every user's background jobs (status, owner,
  attempts, expandable payload/result) with status/type filters, the
  cross-source ingestion ledger with deep links into each source, and a
  failing-schedules strip that deep-links to Automations for management.
- **Failures** — failed AI jobs grouped by job type and error family,
  with the count per window, the top error and an estimate of what a
  requeue would do (after deduplication against jobs that are already
  queued or running, and the 200-job cap per action). A confirmed
  action requeues them as fresh jobs — the failed history stays
  untouched and each new job links back to the failure it replaces.
  Full re-runs (autopilot, digests) are labeled as such; global sweeps
  collapse into one requeue; each failure row opens a detail drawer
  with per-row requeue, and related maintenance (the retrieval reconcile
  pass, scheduled sweeps) is linked.
- **Data changes** — the append-only journals in one cross-entity view:
  posting mutations (sync runs, extractions, re-tags, manual edits) and
  skill lifecycle events (created, promoted, deprecated, merged, deleted)
  with actor and outcome filters.
- **Retrieval** — the read-only observation surface for the vector index,
  with URL-addressable sections (`?section=`): an overview (spaces,
  backend, model/dimension, coverage and stale/failed counts, query
  latency, degraded and zero-result share, embed calls/tokens, last
  reindex and recent `vector.*` changes), the spaces table, reindex /
  cutover / maintenance runs with a per-run drawer (stage, progress,
  result counters, bounded failed ids with a truncation marker, scope,
  heartbeat and error), the versioned golden-query quality compare and
  bad-match drawer (ids and scores only), query health (p50/p95,
  candidates, per-view and degraded distribution, zero-result and
  never-sampled states), failure groups by embed provider, indexing,
  cutover gate and maintenance, embed usage by day/space/kind with budget
  versus usage and untagged calls, and the `vector.*` change trail. The
  tab adds a 90d window preset; the audit event trail itself caps at 30d.
  Nothing here writes: cancel, retry, reindex, compare and space
  lifecycle actions link to Tools → Retrieval. A `?detail=<id>` deep
  link opens the matching run, space, golden-query or failure drawer.

The shared overview/security/failures range also accepts custom dates
and Retrieval adds a 90d preset; the overview supports an auto-refresh
toggle (30-second cadence), and the AI activity, security, jobs
(including source runs) and data-changes views export the current
filtered ledger as CSV (capped at 10,000 rows). All aggregation happens
server-side and works identically on PostgreSQL (web/self-host) and the
SQLite desktop profile.

## Related

- [Privacy and security](privacy-and-security.md) — how keys are stored
- [Getting started](getting-started.md) — the first provider setup
- [Feature catalog](features.md) — what each AI task powers
