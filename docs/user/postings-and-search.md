# Postings and search

Career Assistant connects to live job boards so the catalog meets the real
market. Postings flow through the same machinery as catalog jobs — seen,
saved, alerts — and your deterministic fit score carries over.

## Connectors

A connector SDK ships first-party engines for what is free and legal:

| Engine | What it reads |
|---|---|
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
Every posting tracks your saved → applied funnel.

## Deep extraction

A queued LLM pass turns a posting into auditable data:

- **Skills** with a required level 1–10 and a priority, each backed by a
  **verbatim evidence quote**.
- **Salary**, **responsibilities** with time splits, and **seniority**.
- **Extraction v2** adds contract type, work hours, schedule cues, travel
  demand, onsite policy and **typed benefits** — each with its own evidence.

Low-confidence fields are **suppressed for review, never guessed**.

### Lifestyle constraints gate postings

If a posting conflicts with your constraints (for example a schedule you
cannot work), it is **flagged on the card, never hidden**.

### Skill-level search and provenance

Search vacancies by "skill X at level ≥ N" and rank them by deterministic
coverage of your skills. Every card shows its provenance: raw → fast-mapped →
extracted.

## The Explore page

**Postings → Search** (`/postings/search`) filters every structured field —
including contract type, travel, schedule cues, benefits and organization —
with live facet counts. You can:

- **Save searches** and schedule them (see
  [Notifications and scheduler](notifications-and-scheduler.md)).
- **Paginate by cursor** through large result sets.
- Open a posting's detail page for a **per-posting match score** built from
  the extracted data, weighted by your fit sliders and stale-proof, plus
  source attribution and similar roles.

The **Postings feed** (`/postings`) is the discovery view of everything
available, ordered unseen-first.

## Semantic search

Postings embed into a portable vector store (pgvector optional; plain
Postgres and SQLite are fully supported). Explore's relevance search fuses
lexical and semantic rankings — semantic is a **ranking signal, never a
filter gate**, so your hard filters always hold.

Task-steering AI instructions ship as versioned, audited **skill packs**.

## Organizations are entities

Postings resolve onto a normalized **organization** through a matcher that
folds legal-suffix and spelling variants into aliases. Duplicates merge under
admin review, and "top hiring orgs" aggregates by entity, not by label.

## Related

- [Career Autopilot](career-autopilot.md) — let an agent search for you
- [Matching and rankings](matching-and-rankings.md) — the fit score postings inherit
- [Feature catalog](features.md#postings--live-search) — the full pipeline
