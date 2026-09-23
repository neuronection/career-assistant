# Universities and pathways

If you are choosing an education route, Career Assistant can hold your
university admissions data and connect degrees to jobs. The whole feature is
**manual-review by design**: parsed data is a draft you approve, never an
official feed.

> University intake is gated behind the student career stage (see
> [Career stages](assessment.md#career-stages)); it is hidden for other
> stages.

## Upload your admission PDF

Open **Catalog → Universities** (`/catalog/universities`) and upload your
university's admission PDF (for example the annual "base of admission"
document). An AI parsing pipeline extracts:

- **Universities**
- **Departments**
- **Yearly admission baselines** (scores/ranks per year)

The parse runs as a background job; the result is a **reviewable draft**, not
a write.

## Approve every write

Review, edit, then apply. Parsed data never lands in the catalog unreviewed.
Each extracted row shows what was read and where, so you can correct the
pipeline before it becomes data.

## Degree-to-job pathways

Departments link to jobs through **rich link rows**:

- Relevance to the job
- Required subjects
- Salary band
- Employment rate

So "which degree leads here?" has a real, structured answer rather than a
guess. Open a university detail page (`/catalog/universities/:id`) to browse
its departments and their pathways.

## Career paths

Alongside the degree links, **career paths** describe routes to each job —
curated and AI-drafted — computed over the catalog's typed relation edges.
See [Explore the job catalog](explore-the-catalog.md#career-paths-as-data).

## Related

- [Explore the job catalog](explore-the-catalog.md) — the jobs degrees lead to
- [Career stages](assessment.md#career-stages) — why the feature is gated
- [Feature catalog](features.md#universities--pathways) — the full pipeline
