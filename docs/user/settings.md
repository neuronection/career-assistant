# Settings reference

Settings live under `/settings`, grouped in a two-pane shell with a section
rail. This page explains each page and its purpose.

## Account (`/settings/account`)

Account self-service — every signed-in user, on any instance mode:

- **Profile** — your name, email and admin badge, plus the profiles your
  data is scoped to: create additional profiles and choose which one is
  the default. Switching the active profile stays in the top bar.
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

Admin-only, two tabs. **Web search** ships SearXNG plus five keyed
providers — Tavily, Brave, Exa, Serper and Google Programmable Search;
the first enabled provider that answers wins. Each provider renders as a
card with its priority badge and connection status; the card's **⋯ menu**
carries enable/disable, reorder, test, edit and delete, and **Add
provider** opens a choose-then-configure wizard. See
[Add a job source](add-a-job-source.md) and
[Import extensions from git](import-extensions-from-git.md).

**Connectors** hosts the job-source instances: grouped by what they feed —
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

Connectors also hosts the **MCP server** surface as section cards: the
endpoint URL with the write-access switch, the token lifecycle (mint
shown once, rotate, revoke), copy-ready client setup snippets, the live
tool catalog collapsed behind a searchable disclosure, and the
recent-call audit. The chat-tools GitHub credential sits in the same
card as a disclosure. While the write switch is off, MCP clients see
read tools only. See [MCP access](assistant-chat.md#mcp-access).

## Taxonomy (`/settings/taxonomy`)

Curate the interest tags and the skills ontology (categories, level anchors,
aliases, lifecycle). The catalog, profiles and AI outputs all reference the
taxonomy by stable `key` slugs, so changes here are what keep labels and
translations from breaking data. Unknown skills introduced by users or the AI
appear as `proposed` rows for review.

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
sweeps, each with its next run and last status, plus run-now, pause and
resume. The legacy scheduler deep link redirects here. See
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

## AI audit (`/settings/audit`)

The full AI audit trail: every AI call (task, model, tokens, output, latency)
is recorded. Use it to see exactly what the AI did, with which model, and at
what cost. Rows generated by the dev-only mock provider are marked as
simulated.

## Related

- [Privacy and security](privacy-and-security.md) — how keys are stored
- [Getting started](getting-started.md) — the first provider setup
- [Feature catalog](features.md) — what each AI task powers
