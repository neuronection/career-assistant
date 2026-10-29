# Skill taxonomy & relations

Skills form a small taxonomy: a curated sub-skill tree plus **typed
relation edges** between skills — `is a` (java is a programming
language), `synonym` (ml is a synonym of machine-learning), `part of`
and `related to`. Picking a skill in the posting filters can expand over
those relations, so selecting "programming" also matches postings tagged
java or python.

> Relations are **reviewed data, not scraped guesses**. A background job
> proposes edges from evidence in your own data (skills that co-occur on
> postings and jobs, extraction labels that look like synonyms, curated
> parent links) and every proposal waits for an admin decision. Nothing
> changes a filter until a human accepts it.

## The relations admin surface

Open **Settings → Taxonomy**, tab **Relations** (`/settings/taxonomy`;
admin only). It has four sections.

### Review queue

One card per suggested relation, grouped by skill pair, with the
evidence the job saw and where the suggestion came from (AI proposal,
derived from matching labels, or imported):

- **Accept** — approve the edge. Approved `is a` edges also fill an
  empty place in the sub-skill tree, so the taxonomy reflects the
  decision immediately. If accepting would create a cycle, the app
  refuses and the suggestion stays in the queue.
- **Dismiss** — write the negative edge: this pair + relation never
  comes back as a suggestion.
- **Save as alias** — shown when the suggestion pairs a raw label row
  ("js") with a real skill (JavaScript). The label becomes an alias of
  the real skill — matching resolves it from then on — and the edge is
  dismissed, because a label is not a relation.

**Select mode** adds bulk review: pick any number of cards (or all at
once), then one **Accept** or **Dismiss** applies to the whole batch. Only
rows that actually change state are counted; a row the backend refuses
(for example an `is a` that would close a cycle) is reported back instead
of failing the batch.

**Select mode** adds bulk review: pick any number of cards (or all at
once), then one **Accept** or **Dismiss** applies to the whole batch. Only
rows that actually change state are counted; a row the backend refuses
(for example an `is a` that would close a cycle) is reported back instead
of failing the batch.

**Reading the hints.** The save-as-alias hint appears only when the
proposed label actually looks like a raw-label duplicate of the other
skill — a prefix, an initialism (JS/JavaScript), or contained words. For
rows where the proposed side is a genuinely new skill, the card instead
reminds you that **accepting the edge won't activate it** — promote the
skill too (Skills tab → Select proposed → Promote).

### Corroboration

Unresolved extraction labels enter the queue as proposed skills. A label
that **two different postings** extract corroborates itself and promotes
to the active catalog automatically — the decision is stamped into its
provenance. Everything else (single-posting labels, user-reported or
CV-parsed skills) waits for your promotion, as before.

The Skills tab has the same Select mode for the skill list itself —
**Promote**, **Deprecate**, **Restore**, **Merge** into a chosen active
skill, and **Delete** (behind a confirm). Each button shows how many of
the selected rows it applies to, and a *Select proposed* shortcut grabs
every AI-proposed skill at once. Bulk delete skips skills still
referenced by jobs or profiles and lists them with the reason —
deprecate those instead.

### Graph

The **Graph** tab draws the reviewed taxonomy: every reviewed skill
(active or deprecated) is a node (colored by status) and every approved
relation an edge (colored by relation type). Parent links set by hand
that have no relation row yet count as `is a` edges, so the curated tree
is always visible. Proposed skills stay out of the picture — they are
unreviewed extraction labels (often hundreds) and belong to the review
queue, not the catalog graph.

- Switch between the **force** layout (organic clusters) and the
  **hierarchy** layout (containers above their members — an `is a` child
  sits under its parent).
- **Find…** dims non-matching skills; Enter centers the first match.
- Click a node for its detail card (key, category, status, relation
  count); the card's *Center* button zooms to it.
- **PNG** exports the whole graph, tightly cropped.

Only approved relations render — proposals stay in the review queue
until you accept them, and dismissed pairs never appear.

### All relations

The same cards for every relation regardless of state, plus a manual
editor: pick two skills, a relation type and an optional confidence, and
add — several relations between the same pair are allowed. Manual edges
are trusted on arrival (approved immediately); the remove button
hard-deletes an edge (dismiss keeps the negative edge instead).

> Tree placement carries provenance. An accepted `is a` edge fills the
> skill's untouched place in the sub-skill tree, and the placement is
> remembered as machine-placed; a parent you set in a skill edit (send
> `parent_id: null` to clear it — an edit that omits `parent_id` leaves
> the parent alone) is remembered as yours, and the catch-up never
> overwrites or re-fills it. Removing or dismissing the edge that
> justified a machine placement un-fills it, so the undo works from
> either side. Placements made before provenance was tracked keep their
> previous sticky behavior.

### Thresholds

The discovery job's knobs: minimum co-occurrence support, pairs per AI
call (max 40), pairs per run, and the confidence bar under which a
negative verdict settles a pair without writing anything.

### Runs

The statistics of each discovery run — candidates, batches judged,
edges proposed, negatives, the tree fill counts — and the run's
watermark. A run that capped out, failed or ran without an AI provider
shows its watermark as **held**: its unfinished pairs are re-examined
next run instead of being lost.

## How relations affect posting filters

The Skills section of the posting filter rail carries the match mode:
**Exact**, **Sub-skills** (default) or **Related**, with a 1- or 2-hop
limit for learned edges. Accepted relations widen those matches; the
curated sub-skill tree and synonyms always count for free, and as the
tree fills up, reach grows at the default setting.

## Skill pages

Every skill also has a first-class page at [`/skills/:key`](skills.md) —
stats, positions, the approved subgraph and the lifecycle history in one
place, with the admin actions in the header. The skills table here gains
a **Details** preview with the same numbers and the newest events, and
graph nodes open the page from their right-click menu.
