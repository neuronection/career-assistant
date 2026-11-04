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

## Job cards

Each card in the grid reads like a posting card: the same anatomy, the same
information density, and only facts the catalog actually has.

- **Metric rail** — the number of **open live roles** mapped to the job and
  the **salary band** (median, falling back to entry or senior). Either value
  is omitted when there is no honest number.
- **Body** — the title and job family, a two-line description, meta facts
  (education, typical experience, contract, travel, schedule cues and work
  hours) and the work-style/physical summary.
- **Skills** — required skill chips with their 1–10 levels; click a chip for
  the skill peek. The job's interest chips follow.
- **Footer** — the family/source reference and a **"N open roles →"** link
  to `/postings?job=<code>`, which opens the Postings page already filtered
  to the live openings mapped to this catalog job.

A narrow container can use the compact card density; it keeps the metric rail
and skill chips and drops the description and interests.

## Filtering the catalog

The catalog filter rail speaks the same language as Postings (`/postings`):

- every multi-value axis is **tri-state** — click a chip to include, click
  again to exclude, click once more to clear. A selected value carries an
  **×** that clears it in one click.
- **skills** have per-skill minimum levels, a global minimum level, any/all
  mode and a separate exclude picker.
- **family** is the coarse axis: the family nav on the left writes the same
  `family` parameter, so the two never fight. The rail continues with
  interests, education, demand, salary band, contract, schedule, travel,
  experience, environment and **has open roles**.
- every value shows its live facet count. A value with zero matching jobs is
  disabled instead of silently returning an empty list.
- the header strip shows the result count, the active-filter chips with
  one-click removal, **Clear all** and the sort: **title**, **demand**,
  **salary**, **open roles** or **family**. The catalog list is insight-free
  — fit and match live on `/rankings`, never on this shareable list.

**The URL is the state.** `/catalog?family=technology&skills=programming@6&demand=hot&sort=open_roles`
is shareable, survives a reload and keeps the family nav and the rail in
sync. Unknown or malformed values are dropped and the URL is canonicalized in
place.

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

Below the structured attributes sit two read-only match rails:

- **Similar catalog jobs** — published jobs nearest this one by long-text
  views (summary, requirements, responsibilities, skills). Each card opens a
  drawer with the overall score and the per-view cosine behind it, and links
  to the job.
- **Live postings for this job** — the live openings nearest this job under
  the feed's visibility rules, with the same score drawer and a link to the
  posting.

Both answer from the vector store when it is available and fall back to the
deterministic list (shared skills, or the postings already mapped to this
job) otherwise — the fallback is labelled with the reason, never hidden or
faked.

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
