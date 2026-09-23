# Explore the job catalog

The catalog is the app's knowledge core: a job **family tree** plus a typed
**relation graph**, with rich structured attributes per job. It is
first-class data, not UI decoration — every relation carries weight,
rationale and source, and everything references the taxonomy by stable `key`
slugs so labels can change without breaking your data.

## The family tree

Open **Catalog** (`/catalog`). Job families form the left rail
(`catalog-families`, with job counts); the content pane shows search, recent
searches, drill chips for the active family's children
(`catalog-subfamilies`) and a grid of job cards. Selecting a family and
drilling one level keeps the whole surface usable on narrow screens.

- **Search** across the catalog from the top of the pane.
- **Recent searches** let you jump back to a previous query.
- A job card opens the job detail page.

## The relation graph

Switch to the graph view (`/catalog/graph`) to see jobs as nodes and typed
relations as edges. The five relation kinds are:

| Relation | Meaning |
|---|---|
| `similar_to` | Adjacent roles with overlapping work |
| `specialises_into` | A more specific version of this role |
| `leads_to` | A common next step from this role |
| `alternative_to` | A different route to similar outcomes |
| `prerequisite_of` | Something you typically do before this role |

"what's adjacent to this?" and "what does this lead to?" are traversals over
these edges — not guesswork.

## Job detail

Every job page shows its structured attributes:

- **Interests, skills and work style** — the taxonomy links that drive
  matching.
- **Education and prerequisites** — what you need first.
- **Salary bands and demand outlook.**
- **Physical demands and environments.**
- **Typical positives and negatives** — an honest read on the role.

From the detail page you can score the job (see
[Matching and rankings](matching-and-rankings.md)), practice an interview
(see [Interview prep](interviews.md)) and open related jobs.

## Extend the catalog with AI

The catalog is not fixed. Use **Catalog → Generate** (`/catalog/generate`)
to add new careers with AI: the generator maps its output onto the existing
taxonomy, so a new job is connected to real interests and skills rather than
becoming an orphan of free text. Generated jobs land in the catalog for you
to review and use.

## Career paths as data

Curated and AI-drafted **career paths** describe routes to each job, computed
over the typed relation edges. This is what powers "jobs that lead here" and
experience-first path ordering (which reorders by your
[career stage](assessment.md#career-stages)).

## Taxonomy

Underneath the catalog sits the taxonomy:

- **Interest tags** — the vocabulary of what people are into.
- **Skills ontology** — key, label, category, description, subskills, 1–10
  level anchors, aliases, and a `proposed → active → deprecated` lifecycle.
  Skills and interests link to jobs through FK join tables, never JSONB.

Admins can curate the taxonomy in **Settings → Taxonomy**. Unknown skills
that you or the AI introduce appear as `proposed` rows for review — the
vocabulary grows deliberately.

## Related

- [Matching and rankings](matching-and-rankings.md) — score the jobs you find
- [Universities and pathways](universities.md) — which degrees lead to them
- [Postings and search](postings-and-search.md) — find live openings
