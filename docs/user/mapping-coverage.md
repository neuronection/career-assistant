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
flag, weak mapping and title. The decision trace (the eye icon) shows the
outcome, matching signals, top candidates, the latest extract attempt, a
proposal failure marker and the journal — never AI prompt text.

The state order is **mapped → ignored → detail failed → no description →
detail not fetched → extract failed → not extracted → needs review →
actionable reasons → machine-terminal → unknown**. `detail failed` means
the detail page was never fetched and the fetch-attempt budget is
exhausted; a fetched posting whose extraction failed is `extract failed`.

**Latest recorded attempt.** The funnel reads the extract outcome recorded
on the posting, not whether an extract job ever failed. A successful
extraction (including the already-extracted skip) sets `succeeded` and
overwrites a previous failure; a **terminal** failure records `failed`; a
retryable failure leaves the previous status, and a queued/running retry is
shown as a pending chip in the trace. A `resolve` replay never changes the
status.

Bulk actions (bounded at 200 per action):

- **Extract** — queue the deep extraction for postings that have a
  description (already-queued ones are skipped). The result note reports
  the **queued** count.
- **Re-decide** — re-run the mapping decision (deduped while a run is
  pending). The result note reports the **queued** count.
- **Map selected to…** — one published, non-retired catalog type for the
  whole selection, resolved once. Rows already on that type are reported
  **already**, unknown or terminal (`expired`/`hidden`) rows are **blocked**,
  and the rest map **manual** with the ignore overlay, margin and proposal
  cleared. One audit event carries the mapped/already/blocked counts and
  every mapped row keeps its own journal entry; the result note reports the
  **affected** (mapped) count.
- **Ignore / Unignore** — the reviewed "no good type" overlay; a mapped
  posting must be unmapped first.
- **Unmap** — clear a wrong mapping; the posting returns to triage.
- **Mark reviewed** — clear the extraction-confidence flag.

Each row also carries three direct actions: **Fetch detail now** (one
connector call, no enrichment run and no attempt-budget increment; a changed
description resets the stale extract and queues the normal re-extract),
**Retry extract** (the existing one-posting extract action) and
**Re-propose** (queues the refresh-redecision path, so a failed proposal can
be retried without waiting for the next sweep).

The trace's picker searches the **server-side published catalog** with a
debounced query and a 50-row page; the trace's candidates stay pinned first
with their titles. There is no 200-row truncation disclaimer.

### Weak mappings

A mapping is **weak** when the deterministic coverage margin is below the
policy's δ (δ defaults to 0.08) or when a semantic mapping's confidence is
below 0.65 — two candidates were close enough that a human should look.
Weak rows stay **mapped** (the funnel does not add a new state); the triage
queue marks them with a **Weak** chip and filters on `weak`. New
deterministic mappings write the margin immediately; pre-existing rows stay
empty until the owner runs **Re-decide stale mappings**, and semantic/manual
mappings deliberately leave it null. The quality sample reserves half its batch for weak rows
before the source-stratified remainder, and the Quality view reports the
weak bucket (including the empty-until-sweep note). Nothing is unmapped
automatically.

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

The Runs view also carries the owner-run **Re-decide stale mappings**
action: after confirmation it queues one bounded `POSTING_REMAP` sweep over
active non-manual mappings whose `mapping_version` is missing or older than
the current score version (the after-S1 backfill), and reports how many rows
are in the run. **Force all** re-decides every active non-manual mapping,
including current ones (a forced recompute/rollback); it has its own
confirmation. Neither action is automatic, and neither touches manual or
terminal postings.

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
