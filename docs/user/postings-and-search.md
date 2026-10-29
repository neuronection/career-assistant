# Postings and search

Career Assistant connects to live job boards so the catalog meets the real
market. Postings flow through the same machinery as catalog jobs — seen,
saved, alerts — and your deterministic fit score carries over.

## Connectors

A connector SDK ships first-party engines for what is free and legal.

**Three real job boards work zero-config today** — add a source, sync,
done: **Arbeitnow** (German/European board), **Remotive** and
**Jobicy** (remote-jobs boards). All three are free public APIs that
need no account or key, cap themselves to polite request budgets, and
carry a link back to the original posting (the boards' terms ask for
exactly that credit). Two notes from reality: Arbeitnow's board rotates
fresh listings hourly, and Remotive's site-level robots policy means
some self-hosted setups need the admin's explicit go-ahead before that
board syncs — the app surfaces it as a clear, typed error rather than
fetching silently.

| Engine | What it reads |
|---|---|
| **Arbeitnow** | The live Arbeitnow job board (zero config) |
| **Remotive** | Remotive remote jobs (zero config) |
| **Jobicy** | Jobicy remote jobs, API v2 (zero config) |
| **ATS API** | Public applicant-tracking-system job APIs |
| **JSON-LD** | `schema.org/JobPosting` structured data |
| **RSS** | Job feeds |
| **CSV** | Exported spreadsheets of postings |
| **Paste-a-URL** | A single posting you point at |

Anyone can add more as plugins, opt-in by an admin through the entry-point
registry. Configure sources in **Settings → Scheduler** (source sync) or on
the Postings page.

### How postings map to the catalog

Postings map onto the catalog by **literal skill-ID intersection** — never
label matching. They inherit your fit score with adjustments for freshness,
remote work and seniority, with **no per-posting AI** for the base mapping.
Every posting tracks your saved → applied funnel. **Track application**
on a posting's detail creates the pipeline row and opens the
[application tracker](applications.md), where the same application moves
through screening, interview and offer with a full event timeline and
configurable follow-up reminders.

## Deep extraction

A queued LLM pass turns a posting into auditable data:

- **Skills** with a required level 1–10 and a priority, each backed by a
  **verbatim evidence quote**.
- **Salary** (with the stated gross/net basis and an annualized range),
  **responsibilities** with time splits, and **seniority**.
- **Prerequisites** — the stated gates outside the skill axis (degree
  wording, certificates, licenses), each with its own evidence quote.
  Certificates and licenses are matched against your profile's
  certification entries in the fit score; unmatched ones show as "not
  evidenced", never silently ignored.
- **Extraction v2** adds contract type, work hours, schedule cues, travel
  demand, onsite policy and **typed benefits** — each with its own evidence.

Low-confidence fields are **suppressed for review, never guessed**.

### Lifestyle constraints gate postings

If a posting conflicts with your constraints (for example a schedule you
cannot work), it is **flagged on the card, never hidden**.

### Skill-level search and provenance

Search vacancies by "skill X at level ≥ N" and rank them by deterministic
coverage of your skills. Every card shows its provenance: raw → fast-mapped →
extracted. Skill chips on the cards (and on the posting detail page) are
clickable — they open a compact skill peek (summary, stats, level anchors
and related skills) with a link to the skill's full page.

### Matching skills — exact, sub-skills or related

The Skills section of the filter rail carries a **match mode**:

- **Exact** — only the skills you picked match.
- **Sub-skills** (default) — also matches synonyms and the sub-skill
  tree, so filtering for "programming" finds postings tagged java or
  python.
- **Related** — additionally matches part-of and related-to skills.

**Hops** (1 or 2) bounds only the *learned* edges — the relation
proposals and imports. The curated sub-skill tree and synonyms always
count for **free**: they are not part of the hop budget. So the default
setting widens on its own as reviewed relations fill the tree, and the
hop knob is only needed for chains of learned edges (java → JVM
languages → programming at 2 hops). **Exact** is always one click away.
See
[Skill taxonomy & relations](skills-taxonomy.md) for how proposals are
reviewed before they ever widen a filter.

## The Explore page

**Postings → Search** (`/postings/search`) is the Postings default and
filters every structured field — including contract type, travel, schedule
cues, benefits and organization — with live facet counts. The filter rail
speaks the same language as the feed's:

- every multi-value axis is **tri-state** — click a chip to include, click
  again to exclude (rendered struck in red), click once more to clear;
  right-click excludes directly,
- **skills** use the type-ahead picker with the browse-catalog modal and a
  per-skill minimum level, plus a second picker for **excluded skills**,
- **organization** is picked from the companies catalog (search popup)
  with its own exclude list,
- **sources** are include/exclude chips with live counts.

You can also:

- **Save searches** and schedule them (see
  [Notifications and scheduler](notifications-and-scheduler.md)).
- **Scroll** — results load infinitely: the next page fetches
  automatically as you approach the end (cursor pagination under the
  hood).

## Opening a posting

Clicking a posting card opens the posting **inside the app** at
`/postings/:ref` — nothing is lost to a third-party tab. The page shows
everything the system knows about the role:

- the full **description** captured from the source,
- **key facts**: location, work mode (remote / hybrid / on-site with
  office days), employment and contract type, seniority, work hours with
  the weekly range, travel demand, education, languages, and the salary
  range with its annualized figure,
- a **timeline** — posted, first seen, last updated and expiry, each as
  "3 days ago" with the exact date beside it,
- **categories** — the mapped catalog role (with your interest tags and
  the typed benefits) — and the skill requirements with level, priority
  and their verbatim evidence quotes,
- your per-posting **match score** with the per-dimension breakdown,
  source attribution and similar openings.

"Open on the original board" (the top button) jumps to the listing in a
new tab and records the click; beside it sit the cover-letter draft, the
practice interview and the [application tracker](applications.md) entry.

The **Postings feed** (`/postings/feed`) is the discovery view of everything
available, ordered unseen-first. **Search is the default landing** —
`/postings` opens the Explore page.

## Semantic search

Postings embed into a portable vector store (pgvector optional; plain
Postgres and SQLite are fully supported). Explore's relevance search fuses
lexical and semantic rankings — semantic is a **ranking signal, never a
filter gate**, so your hard filters always hold.

Task-steering AI instructions ship as versioned, audited **skill packs**.

## Organizations are entities

Postings resolve onto a normalized **organization** through a layered
matcher: a quality gate rejects junk labels ("Confidential", staffing
agencies), exact keys match slug / alias / initialism / company domain
(so `P&G` and `Procter & Gamble` land on one company), and only strong
fuzzy scores link without asking. Learned name variants persist as
reviewable alias rows, per-pair "never link" exclusions keep
similar-but-different employers apart, and near-misses queue for the AI
arbiter — a confident match links, a confident "different" creates the
new company, anything unsettled becomes a merge suggestion. Filter the
feed by company with the `company` chip or the **no company** audit
filter on `/postings/feed`, and open any card's company name to see all
of that employer's postings on `/companies/:key`.

## Related

- [Career Autopilot](career-autopilot.md) — let an agent search for you
- [Matching and rankings](matching-and-rankings.md) — the fit score postings inherit
- [Feature catalog](features.md#postings--live-search) — the full pipeline
