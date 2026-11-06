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

## How extraction resolves skill labels

Deep extraction never asks a model to pick from the whole skill catalog.
The catalog keeps growing, and putting every active key in every prompt
would cost more with each posting while inviting the model to echo a key
that is not quite right. Instead the work is split into two bounded
passes:

1. **Read the posting, not the catalog.** Pass 1 records each skill label
   verbatim — the words the posting actually uses — with its required
   level, priority and the evidence quote. It cannot force the label onto
   an existing skill, so a genuinely new skill surfaces honestly.
2. **Propose candidates, then adjudicate.** A deterministic matcher
   proposes the existing skills each label might mean (an exact key,
   label or alias first; then similar wording; then similar meaning from
   the skill embeddings). One batched AI step then decides, per label,
   between one of **its own** offered candidates and **new**. It cannot
   invent a key; a key outside the offered set is treated as new. Labels
   that already hit an exact key never reach this step.

Matched labels tag the posting with the catalog skill (proposed rows
count, so a label can corroborate a skill that is still under review).
New labels become proposed skills and enter the corroboration flow
below. Every label also stores its resolution trail — which route resolved
it (exact, AI verdict or new), the candidate shortlist it saw, and the
verdict's confidence — so the posting itself answers "why is this tagged
X?" later.

## The relations admin surface

Open **Settings → Taxonomy**, tab **Relations** (`/settings/taxonomy`;
admin only). The tab gathers the review queue, the corroboration rules,
the reviewed graph, the manual relation editor, the discovery thresholds,
each discovery run's statistics and the extraction resolution controls.

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

**Near-duplicates never auto-promote.** Before promoting, the app checks
the corroborated label against the active catalog. If an active skill is
already a near-duplicate — the same claimed word, close wording, or a very
close embedding — promotion is **blocked**, the near match and its scores
are stamped on the proposal (`auto_promote_blocked` in its provenance),
and the row stays proposed for you to **Merge**. Nothing is auto-merged:
two labels that mean the same thing must not become two active skills just
because both were seen twice.

The Skills tab has the same Select mode for the skill list itself —
**Promote**, **Deprecate**, **Restore**, **Merge** into a chosen active
skill, and **Delete** (behind a confirm). Each button shows how many of
the selected rows it applies to, and a *Select proposed* shortcut grabs
every AI-proposed skill at once. Bulk delete skips skills still
referenced by jobs or profiles and lists them with the reason —
deprecate those instead.

## The skills & interests listing

Both tabs are searchable, filterable listings rather than plain tables:

- **Search** matches a tag's label, its stable key and — for skills —
  its aliases (for interests, the description).
- **Status chips** narrow the list (all / active / proposed /
  deprecated on Skills; all / active / deprecated on Interests), each
  chip showing how many entries it holds.
- **Collapsible groups** order the list: Skills group by status with
  **proposed first** (the review pile is the work), Interests group by
  their eight categories, each with an icon and a count.
- **Rows are clickable** — a row (or Enter on a focused row) opens a
  **details drawer** instead of cluttering the list with buttons. For
  a skill it shows the same numbers as the skill page — demand,
  average level, users, aliases and the newest history events — plus
  the admin actions: **Promote** on proposed rows, **Deprecate /
  Restore**, **Merge** into a chosen active skill, **Delete** behind a
  confirm, and a link to the full `/skills/:key` page. For an interest
  the drawer edits label, category and description, and carries the
  **Deprecate / Restore** and confirmed **Delete** actions.
- Select mode keeps the bulk bar working exactly as before — the
  checkbox column appears next to the rows only while it is on.

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

### Resolution

The extraction pipeline's own insight and tuning surface, at
`/settings/taxonomy?tab=relations&section=resolution` (admin only). It
answers what the two-pass resolver actually did and lets you tune it
without a deploy:

- **Resolution KPIs.** The last extraction run shows labels, exact hits,
  pass-2 matches, new proposals and gate blocks (and whether it was a full
  extraction or a replay). The rolling tiles cover the selected 24-hour,
  7-day or 30-day window: match rate, new rate, block rate, replay rate
  and degrade rate. Failing schedules are called out with a link to
  [Automations](notifications-and-scheduler.md), where the schedule itself
  lives. The same numbers come from `/admin/taxonomy/resolution/stats`.
- **Thresholds.** The trigram and cosine candidate floors (raising them
  cuts resolver spend by sending weak candidates straight to *new*),
  candidates offered per label (at most 5), the dedup-gate trigram and
  cosine bars, the number of postings that corroborate a label, and how
  many corroborating posting ids a row keeps. A save applies to the next
  run.
- **Waves.** **Replay resolution** takes up to 200 posting ids and
  re-resolves their stored verbatim labels against the current taxonomy —
  matcher plus AI verdict only, no second reading of the posting. This is
  the action to run **after a merge or alias change**: the surviving
  skill claims the old label without re-extracting everything. The report
  counts queued, skipped (already queued or on an older extraction
  version) and missing ids; the bulk wave posts to
  `/admin/postings/replay`. Skill vectors (the matcher's semantic layer)
  are refreshed by the retrieval index's reconcile pass — the daily
  `vector_reconcile` job, or an operator running `scripts/reindex_vectors.py
  --kinds skill`. Without an embed provider the pass reports the degradation
  and the matcher falls back to wording.

## Batch review

Every review queue on this page batches the same way. Click **Select** in
the queue's toolbar; a checkbox appears on each card or row and the bar
below shows what is selected.

- **Select all names its scope.** The checkbox selects what the current
  search and status pills match; the caret beside it offers the named
  subsets — the proposed skills, the archived variants, the translations
  of the current language — and *Deselect all*.
- **Hidden selections are never silent.** Changing a filter keeps your
  selection; the bar reports how many selected rows the filter hides and
  offers *Show* (clear the filters) or *Drop* (deselect them). A
  destructive confirmation restates the count and the hidden subset.
- **Actions show what they will do.** Each button carries the number of
  selected rows it applies to — promoting only proposed skills, restoring
  only deprecated ones, deleting everything selected.
- **Keys:** `Esc` leaves selection mode, `Ctrl/⌘+A` selects what the
  current filters match, and `Shift`-click extends a range.

Which queues batch what: interests (deprecate/restore/delete), skills
(promote/deprecate/restore/merge/delete), relations (accept/dismiss),
translations (approve/reject), enrichment proposals (apply/discard), draft
paths (publish/reject), job proposals (dismiss only — mapping or creating a
job type is a per-row action) and CV variants (archive/restore/draft/
activate/delete).

## Paths & enrichment review

Two further tabs on the same page moderate AI- and user-authored
catalog content:

- **Paths** lists career paths that are still **drafts**. Each card
  shows the route icon, status, the target job (title plus its stable
  code), the description and the **source** the path came from, with
  the steps as compact numbered chips — a kind icon (job, skill,
  education, certification, experience, milestone), the skill or
  family label the step resolves to, and an **optional** badge where
  it applies. The full step list — edge labels, education levels and
  the stable keys — stays available behind **Show all steps**.
  **Publish** moves the path into the catalog; **Reject** asks for
  confirmation first and drops it from the review list.
- **Job proposals** are the postings whose catalog join found no type. A
  card shows the **source posting** (raw title, employer, link, seniority)
  separately from the **proposed job type** — an occupation archetype, not
  the posting title. The primary action follows the proposal: **Map to
  <type>** when an existing catalog type covers it (one confirmation, no new
  job), or **Create job type** with an editable title, family and
  archetype-level description. Closest catalog types are buttons, and
  **Browse catalog…** opens a searchable published-job picker. An exact or
  near duplicate title warns and offers "Map to existing" or an explicit
  "Create anyway"; the deterministic naming guard refuses a department-only
  or bare-level title unless you override it deliberately. **Re-decide**
  queues the background re-run, and the **old proposals** banner regenerates
  or clears legacy v1 rows. Below the queue, **Catalog hygiene** lists
  duplicate published types and retires one into a survivor with every
  posting re-decided and one audit record.
- **Enrichment** lists AI proposals for job attributes that wait for a
  human decision. Known proposal fields render as labeled rows —
  contract type, working hours, schedule cues, travel and benefits as
  translated chips (lists as chip rows), the model's note as plain
  text — and anything the interface does not know yet collapses into a
  **Raw proposal** disclosure, so a proposal is never reduced to debug
  JSON. **Apply** merges the proposed fields into the job,
  **Discard** (behind a confirmation) drops the proposal, and each
  card shows when it was proposed.

Both queues on the tab are **paged**, so a long backlog never ships as one
page. The enrichment cards load 25 at a time and the job-proposal queue
below loads 50 at a time; both append the next window automatically as you
scroll (the same auto-load the postings list uses), and a **Load more**
control stays on the proposal queue as a manual fallback. Applying or
discarding a card removes it in place — the queue you already scrolled
through stays where it is, and the tab badge recounts from the server.

## Translations review

The **Translations** tab is the catalog-translation queue — it used to
sit above every taxonomy tab and now lives as the page's own sixth
segment. AI drafting fills it with localized labels for jobs, skills,
job families and the institution kinds (universities, departments,
metric dimensions, assessment and CV templates) in **de** and **el**.
A draft never renders: approval is the only route to the catalog,
search, rankings, chat and CV surfaces.

- **Locale and status pills carry live counts.** The queue opens on
  the German drafts; statuses are draft (the work), approved
  (rendering everywhere) and rejected (never renders).
- **Search** matches the base label and the drafted translation, so
  you can look up either side of a row.
- **Cards group by entity kind** — jobs and skills first, then
  families and the institution kinds — and every card shows the
  **base label next to the draft**, so a translation is judged against
  its source, never blind. Edit the wording inline, then **Approve**
  or **Reject**.
- **Select mode** batches the decision: **Approve** or **Reject**
  applies to every selected draft of the current locale; batch reject
  asks for confirmation, and rows the backend refuses are reported
  individually instead of failing the batch.
- Long queues **load more** in pages instead of rendering everything
  at once, and **Draft with AI** fills the queue with new drafts (the
  result note reports how many landed). Re-drafting brings rejected
  rows back as fresh drafts.

University names stay authoritative: an overlay may translate the
display label, never rewrite the stored name.

## How relations affect posting filters

The Skills section of the posting filter rail carries the match mode:
**Exact**, **Sub-skills** (default) or **Related**, with a 1- or 2-hop
limit for learned edges. Accepted relations widen those matches; the
curated sub-skill tree and synonyms always count for free, and as the
tree fills up, reach grows at the default setting.

## Skill pages

Every skill also has a first-class page at [`/skills/:key`](skills.md) —
stats, positions, the approved subgraph and the lifecycle history in one
place, with the admin actions in the header. The Skills tab's rows open
a preview drawer with the same numbers and the newest events, and graph
nodes open the page from their right-click menu.
