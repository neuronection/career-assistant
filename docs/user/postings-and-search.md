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

More sources can be added as **extensions** — connectors imported from
git or registered as MCP script sources by an admin in
**Settings → Tools → Connectors**. External code never runs inside the
app: imported connectors are sandboxed or external processes, and each
source gets its own management page for configuration and syncs.

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

**Postings** (`/postings`) — the page IS the search, and it filters
every structured field — including contract type, travel, schedule
cues, benefits and organization — with live facet counts. The filter rail
speaks the same language as the feed's:

- every multi-value axis is **tri-state** — click a chip to include, click
  again to exclude (rendered struck in red), click once more to clear
  (right-click jumps straight to exclude). Every selected chip carries an
  **×** that clears it in one click, so you never have to cycle back out,
- **skills** use the type-ahead picker with the browse-catalog modal and a
  per-skill minimum level, plus a second picker for **excluded skills**
  (their chips render in the same excluded red as every other exclude),
- **organization** is picked from the companies catalog (search popup)
  with its own exclude list (same excluded chip styling),
- **sources** are include/exclude chips with live counts,
- **state toggles** sit under the facets: deep-extracted only, saved
  only and **Hide seen** — reviewed postings drop out of the list without
  touching the other filters.

### Sorting results

The results header sorts the list without changing the filters: **Best
fit** (the default), **Newest** (posted date), **Highest salary**
(annualized range; unknown salary sorts last) and — once you type a
search query — **Relevance**, which fuses the lexical match with the
semantic ranking. Changing the sort restarts the list at page one; the
fit score stays on every card whichever order you pick.

**Every filter and the sort live in the URL** — the address bar carries
the whole search (`/postings?sort=salary&seniority=mid&seen_exclude=true`,
skills as `skills=programming:4`, organizations as repeated `org=` values).
A reload, the browser's back button and a shared or bookmarked link all
open the same filtered view; unknown or malformed values are dropped and
the page falls back to its defaults.

### Presets — save a view, not a query

Above the results sits the **preset bar**. *Save current view* turns the
whole search — text, every facet, the state toggles, the sort — into a
named preset chip:

- **Click a chip** to re-apply it; the active preset is highlighted.
- **`⋯` on a chip** shows exactly what the preset holds (search, skills
  with levels, included/excluded facets, salary floor, toggles, sort) and
  offers **Update with current filters**, **Rename** and **Delete**
  (confirmed; the postings stay).
- When the current view *is* a preset, the save button becomes
  **Update <name>** instead of creating a duplicate; names are unique
  per user. Presets are saved searches, so they can also be scheduled
  from [Notifications and scheduler](notifications-and-scheduler.md).

You can also:

- **Scroll** — results load infinitely: the next page fetches
  automatically as you approach the end (cursor pagination under the
  hood).

### Seen, at a glance

A posting is marked seen when you open it or send an application, and
the **"Mark as seen"** action in an unseen card's status line marks it
seen without opening anything — one click, no menu, and the same slot
then shows the quiet double-check. Seen cards stay fully readable
(nothing is dimmed): that double-check and a **neutral bar down the
card's left edge** identify them, so a long results list separates fresh
openings from ones you already reviewed. Marking is one-way.

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

The posting detail always shows your **canonical** match score. When an
[autopilot goal](career-autopilot.md) turns a profile input off, that
run's ranking scores the disabled dimension at a neutral 7/10 with a
visible "disabled for this goal" note instead of a penalty — scores stay
comparable across goals. Prerequisites merge over the inputs still in
play, so switching one off can only raise or keep the merged
prerequisite score, never lower it, and postings still awaiting deep
extraction (estimates) ignore the toggles entirely.

"Open on the original board" (the top button) jumps to the listing in a
new tab and records the click; beside it sit the cover-letter draft, the
practice interview and the [application tracker](applications.md) entry.

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
new company, anything unsettled becomes a merge suggestion. Filter by company with the `company` chip or the **no company** audit
filter, and open any card's company name to see all of that employer's
postings on `/companies/:key`.

## Market pulse rail

The Explore page carries a **market pulse rail** on its right edge:
new-posting counts for the last 24 hours / 7 days / 30 days, a 14-day
volume sparkline, the currently rising skills and the most productive
sources. Every chip that has a matching filter applies it to the feed —
click `New in 7 days` to filter by posted-within, a rising skill to
require it, a source to restrict the feed to it. The full picture lives
on the [market statistics](market-stats.md) page.

## Related

- [Career Autopilot](career-autopilot.md) — let an agent search for you
- [Matching and rankings](matching-and-rankings.md) — the fit score postings inherit
- [Feature catalog](features.md#postings--live-search) — the full pipeline
