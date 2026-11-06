# Mapping coverage & triage (admin)

**Tools → Mappings** (`/settings/tools?section=mappings`) is the admin
console for the job-post → job-type mapping. It answers one honest
question: of the active postings, how many are **mapped** to a catalog job
type, and how many are at least **accounted for** — mapped, finished by the
matcher with no candidate, or reviewed by a human who decided no catalog
type fits.

## The funnel, not a "100% mapped" target

The overview's tiles walk the funnel: active postings → **described** →
**extracted** → **mapped** → **accounted for**. Most "unmapped" postings
are stuck **before** the matcher (never extracted, no fetched detail, no
description) — the console puts those buckets first in the triage queue
with the right lever, instead of sending you to force a link.

The **accounted-for gate** compares the accounted share against the floor.
A mapped rate below 100% is expected: some postings are multi-role, noisy
scrapes or genuinely outside the catalog. The human **ignore** action
records that decision ("reviewed, no good type") and counts the posting as
accounted for — never as mapped.

## Triage

The **Triage** view lists active postings with their funnel state, source,
top candidate and age, filterable by state, source, detail state, review
flag and title. The decision trace (the eye icon) shows the outcome,
matching signals, top candidates and the journal — never AI prompt text.

Bulk actions (bounded at 200 per action):

- **Extract** — queue the deep extraction for postings that have a
  description (already-queued ones are skipped).
- **Re-decide** — re-run the mapping decision (deduped while a run is
  pending).
- **Map** — one posting at a time from its trace: pick **any published
  catalog type** (the trace's candidates are pinned first; search the
  catalog for the rest) and map it (draft/retired types are refused; the
  trace then shows the manual outcome).
- **Ignore / Unignore** — the reviewed "no good type" overlay; a mapped
  posting must be unmapped first.
- **Unmap** — clear a wrong mapping; the posting returns to triage.
- **Mark reviewed** — clear the extraction-confidence flag.

## Types & sources

The **Types & sources** view breaks coverage down per source (detail mode,
funnel counts, top unmapped bucket, last sync) and per catalog job type
(mapped postings, open roles, and a **zero postings** flag for types
nothing maps to yet). The proposed types waiting in the
[Taxonomy → Enrichment](/settings/taxonomy?tab=enrichment) queue appear as
clusters — the console links there, it never creates job types itself.

## Run controls

The **Runs** view shows the three mapping switches (job proposals,
semantic rescue, semantic rerank) **read-only** — they live in
[Taxonomy → Relations → Resolution](/settings/taxonomy?tab=relations), and
the embeddings index lives in
[Tools → Retrieval](/settings/tools?section=retrieval). The console never
duplicates them.

## Policy, quality and alerts

The **Runs** view also carries the editable decision policy (τ_job, δ, the
semantic rescue threshold and the minimum shared skills) with a bounded
dry-run over the oldest triage rows — a dry-run writes nothing, embeds
nothing and spends no AI. Saving is effective on the **next** decision and
every decision records the policy hash in its trace.

The **Quality** view keeps the human golden set and a deterministic
sampled audit, reporting precision/recall/agreement and an **advisory**
gate (never a release gate). The **alert settings** card edits the
accounted-for floor the daily alert sweep evaluates against; the sweep
emits through the normal notification inbox (accounted-for floor breach, a
source that extracts but maps nothing, a failed re-decide run, degraded
semantic signals, aging proposals). The coverage snapshot is captured
daily at 02:45 UTC and the alert sweep runs daily at 02:50 UTC — both
boot-provisioned, no operator step.

## Related

- [Settings reference](settings.md)
- [Explore the catalog](explore-the-catalog.md)
