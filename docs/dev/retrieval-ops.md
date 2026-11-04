# Retrieval operations runbook

This is the operator how-to for the career vector index: where the read and
write surfaces live, how to reindex and cut over a space, how to read a run,
and what to do when a gate or an alert fires. The family contract and its
non-negotiables are the family retrieval-operations contract; this page is the
career runbook, not a second copy of the law.

Everything here is admin-only. The surfaces never expose document, query or
prompt text: counts, ids, scores, reasons, latencies and token usage only.

## 1. Where the surfaces live

| Surface | Route | Role |
|---|---|---|
| Tools → Retrieval | `/settings/tools?section=retrieval` | The write surface: active space, reindex, space lifecycle, maintenance, quality compare, danger zone |
| Audit → Retrieval | `/settings/audit?tab=retrieval&section=overview` | The read-only observation tab: overview, spaces, runs, quality, query health, failures, usage, changes |
| AI activity | `/settings/audit?tab=ai&task=embed` | The raw `ai_generations` ledger for `embed` calls (debugging path) |
| Usage | `/settings/audit?tab=usage` | Embed calls/tokens and the token budget |
| Jobs & runs | `/settings/audit?tab=jobs` | The underlying `background_jobs` rows, including `VECTOR_*` |

The Audit sections are URL-addressable: `?section=overview|spaces|runs|
quality|query-health|failures|usage|changes`. A run, space, golden query or
failure drawer opens with `?detail=<id>`, so an alert can deep-link straight
to the evidence. Nothing in Audit writes; cancel, retry, reindex, compare and
space lifecycle hand off to Tools → Retrieval.

The Retrieval tab is not the AI ledger. Use the AI tab when you need the
embedding prompt or provider error for one call; use Retrieval for the index
state and the run history.

## 2. Reindex by kind, view and since

**Coverage & reindex** on Tools → Retrieval queues one bounded
`VECTOR_RECONCILE` run:

- **Kind** — `posting`, `job`, `profile`, `skill` (all when omitted).
- **View** — `summary`, `requirements`, `responsibilities`, `skills`,
  `body` (all when omitted).
- **Since** — an ISO timestamp; only source rows updated since then.
- **Budget** — embed units for this run (default 2000, max 100000).
- **Limit** — documents per run (default 200, max 5000).
- **Force** — re-embed unchanged content instead of hash-skipping it.
- **Auto-continue** — queue the next bounded batch when this one is partial.

A queued run is reported as queued, never as finished. The action returns
`202` with a run id; the same run is visible in Audit → Runs and in Jobs &
runs. A full reindex is a sequence of bounded runs, not one unbounded scan.
Defaults for batch size (10) and scan limit (500) are for the worker; the UI
normally leaves them alone.

Read the run result from the run drawer (or `GET
/admin/retrieval/runs/{id}`):

| Field | Meaning |
|---|---|
| `scanned` | Source rows inspected in this batch |
| `embedded` | Documents written/updated |
| `skipped` | Unchanged rows hash-skipped (or outside the scope) |
| `failed` | Documents that could not be embedded/indexed |
| `failed_ids` | Up to 500 affected ids; `failed_ids_truncated` says the list was cut |
| `gate` | `pass` / `fail` / `unknown` for the run's own gate evaluation |
| `stage`, `progress` | Worker stage and percentage; not a `run_steps` trace |
| `heartbeat_at`, `error` | Liveness and the terminal failure reason |

A partial run with `auto_continue` queues its successor. A cancelled run
stops after the current batch; `cancel` sets a flag, it does not rewrite the
run's status.

## 3. Build → backfill → gate → activate → remap → retire/drop

A model or dimension change is a **new space**, never an in-place rewrite.
The active space keeps serving reads throughout.

1. **Build.** Tools → Retrieval → **Spaces** → **Build new** (or `POST
   /admin/retrieval/spaces`). Supply the space name, provider, model,
   dimension, metric and optional prefixes. The space starts `building`; its
   physical index is provisioned off the request path. The active row is
   untouched. A matching build is reused idempotently; a different building
   space with the same name is refused until it is retired or dropped.
2. **Backfill.** Queue reindex runs **against the building space** for every
   kind you intend to serve. Backfill writes through the ordinary bounded
   reconcile writer and stamps coverage snapshots against the building space;
   the active space is not modified. Run until the coverage snapshot is
   current for each kind.
3. **Gate.** Open **Quality** and compare the candidate against the baseline
   (`POST /admin/retrieval/quality/compare`). The versioned golden-query set
   must clear recall ≥ 0.80 and precision ≥ 0.50, and the coverage snapshot
   for every selected kind must be at or above the 99.5% gate. A missing
   golden set is an honest refusal, never a fabricated score.
4. **Activate.** Tools → Retrieval → **Activate** (or `POST
   /admin/retrieval/spaces/{id}/activate`). Activation runs the coverage and
   quality checks again, flips the candidate to `active`, retires the previous
   active space in the same transaction, and enqueues the `POSTING_REMAP`
   invalidation for the retired space key. Manual and terminal mapping rows
   are left alone by the remap handler.
5. **Remap.** The activation response and the Changes section show the remap
   job. Watch it in Audit → Runs / Jobs & runs. Do not retire or drop the old
   space until the remap has settled; reads already follow the new active
   pointer.
6. **Retire and drop.** Retire a non-active space (`POST
   /admin/retrieval/spaces/{id}/retire`, typed name). Drop it after the 7-day
   grace period (`POST /admin/retrieval/spaces/{id}/drop`, typed name; `force`
   skips the grace, not the confirmation). The active space cannot be retired
   or dropped. Dropping removes the physical table and metadata and is
   audited under `vector.space.*`.

If the gate refuses activation, the `409` body carries
`activation_gate.reasons`: `coverage_fail` means one or more kinds are below
the coverage gate (backfill them); `quality_below_floor` means the compare
missed recall/precision (inspect the per-query misses in Quality and fix the
content, views or golden set, then re-compare). Never lower the floor to force
a cutover.

## 4. Maintenance actions

**Index maintenance** on Tools → Retrieval queues one typed
`VECTOR_MAINTENANCE` run. Each action is bounded and returns the normal run
result.

| Action | What it does |
|---|---|
| **Index rebuild** | PostgreSQL `REINDEX INDEX CONCURRENTLY` on the space's HNSW index, on an AUTOCOMMIT connection. SQLite has no online rebuild for `vec0`, so it runs `VACUUM` and says so. A linear desktop space skips the physical action honestly. |
| **Vacuum** | PostgreSQL `VACUUM (ANALYZE)` / SQLite `VACUUM`, both on AUTOCOMMIT. |
| **Orphan sweep** | Pages the space's documents and deletes those whose polymorphic source no longer resolves. Dry run counts without deleting. Default limit 500, max 5000. |
| **Retry failed** | Takes the failed ids from the latest failed run and re-enqueues a scoped reconcile for exactly those documents. Dry run previews the count. With no recorded failures it refuses (`409`) instead of scanning the corpus. |

Maintenance never runs DDL on the request path. The physical action is a
`background_jobs` row, visible in Audit → Runs.

## 5. Idempotency, locks and crash recovery

- **Idempotency key.** Every mutating action requires an
  `Idempotency-Key` header (8–120 characters) or the equivalent body field.
  Replaying the same key with the same body within 24 hours returns the
  original run; the same key with a different body is a `409`. The UI
  generates a fresh key per click.
- **One active run per space.** `VECTOR_*` runs take `lock_key =
  vector_space:<space_id>`; a partial unique index over queued/running rows
  enforces it at the database. A second reindex, cutover or activation for
  the same space is refused (`409`) while the lock is held. A build holds the
  space-name lock until the building row has an id.
- **Stale heartbeat.** Workers write `heartbeat_at` every 30 seconds. A
  reaper runs every 60 seconds and fails a running vector run with no
  heartbeat for 15 minutes as `stalled: no heartbeat for 15m`, releases the
  lock, writes `vector.run.stalled`, and lets the next action proceed.
  `recover_orphans` at boot is a second path, not the only one.
- **Retry** re-enqueues a terminal run with its preserved scope under a fresh
  idempotency scope. Cutover/gate evaluations are synchronous and cannot be
  retried as runs; re-run the action instead.

## 6. Alerts, dedup and recovery

Retrieval alerts go through the existing notification funnel only. All ten
kinds are boot-seeded; an unknown or disabled kind fails soft and notifies
nobody. Each is admin-scoped, deduped and recovery-reset.

| Kind | Fires when | Dedup | Manage URL |
|---|---|---|---|
| `retrieval.coverage_low` | Coverage below the 99.5% gate with no active building run | `space` | `/settings/tools?section=retrieval` |
| `retrieval.reindex_failed` | A `VECTOR_*` run reaches terminal `failed` | `space+kind` | `/settings/audit?tab=retrieval&section=runs&detail=<run_id>` |
| `retrieval.reindex_stalled` | A non-terminal run has no heartbeat/progress for 15 min | `run_id` | `/settings/audit?tab=retrieval&section=runs&detail=<run_id>` |
| `retrieval.quality_gate` | The golden-query compare misses recall 0.80 or precision 0.50 | `space` | `/settings/audit?tab=retrieval&section=quality` |
| `retrieval.query_slo` | Query p95 > 1500 ms for 15 min | `space` | `/settings/audit?tab=retrieval&section=query-health` |
| `retrieval.degraded_rate` | Degraded share > 5% over 15 min | `space+reason` | `/settings/audit?tab=retrieval&section=query-health` |
| `retrieval.provider_unassigned` | The embeddings task has no provider/model assignment | `singleton` | `/settings/tools?section=retrieval` |
| `retrieval.index_missing` | The pgvector extension or index is absent on web | `space` | `/settings/tools?section=retrieval` |
| `retrieval.budget_exhausted` | `AIBudget(task_type='embed')` is exhausted | `window` | `/settings/audit?tab=retrieval&section=usage` |
| `retrieval.space_drop_pending` | A retired space is past the 7-day grace | `space` | `/settings/tools?section=retrieval` |

A condition that clears releases its dedup key, so a later recurrence
notifies again; a still-true condition is not repeated inside the dedup
window. Daily caps are per channel. The evaluator is the bounded
`retrieval_alert_sweep` system job on a five-minute schedule; it reads the
latest snapshots, recent runs, 15-minute rollups, the persisted quality
compare and the token budget, never the corpus.

## 7. Honest degraded and cold states

- A space that has never been reconciled says **never reconciled**. It does
  not show a fake 0% or 100%.
- ANN recall is **not sampled** until the maintenance probe runs. That is a
  real state, not a failure.
- An empty install or a space with no golden set reports `empty` /
  `no_golden_set` rather than inventing numbers.
- A degraded query was served from the lexical fallback. Query health shows
  the reason: `provider_unassigned`, `embed_failed`, `index_missing`,
  `space_mismatch` or `over_cap`.
- The backend label is honest everywhere: PostgreSQL pgvector/HNSW, SQLite
  sqlite-vec, or “Linear fallback — desktop scale”. Unsupported maintenance
  actions are skipped with a reason, never faked.
- No raw text rule: Retrieval DTOs, exports and alert payloads carry no
  document, query or prompt text. Raw embed text stays on the admin AI tab;
  the status export is aggregates only.

## 8. Troubleshooting

### Is this posting indexed?

Two ways to answer the same question, both admin-only and aggregate-only:

- Open the posting's detail page — under its facts an admin sees one line
  with the state, the space facts (`name · model · dim · backend`) and the
  record count, linking to Tools → Retrieval.
- Or call `GET /api/v1/admin/retrieval/documents/status?kind=posting&source_ids=<uuid>`
  (repeatable or comma-joined; at most 50 ids — an empty list or more is a
  400, never a silent truncation). `kind` is one of `posting`, `job`,
  `skill`, `profile`.

The read composes the existing document, record and source rows at request
time; nothing is stored or backfilled. The five states:

| State | Reason | Meaning |
|---|---|---|
| `current` | — | Document exists, schema version matches, source hash matches, record count matches. |
| `stale` | `schema_version_mismatch` / `source_hash_mismatch` | Indexed, but the composer version or the composed text changed since the write — reindex that source. |
| `missing` | `document_missing` / `source_unavailable` | No document in the active space, or the source row itself is gone. |
| `incomplete` | `no_records` / `record_count_mismatch` | The document exists but its records are missing or fewer than the composer would write (lost chunks); reindex. |
| `off` | `no_active_space` | No active content space, so nothing is indexed. Cold is not zero — build and activate a space first. |

None of these states gates serving: an unindexed posting is fully returned,
and the semantic paths degrade to the lexical order. That is ADR-0051 §7
(the family vector-retrieval ADR in the dev repo) — semantic is a ranking
signal, never a gate.

| Symptom | Check | Fix |
|---|---|---|
| **No provider / embeddings unassigned** (`retrieval.provider_unassigned`) | Settings → AI → Tasks: the embeddings slot | Assign an embeddings-capable model, then reindex. A fresh install answers 503 until configured. |
| **Missing index** (`retrieval.index_missing`) | Overview/health backend label; PostgreSQL extension | Run **Index rebuild**; confirm `CREATE EXTENSION vector` on web. On SQLite/linear the label explains the fallback. |
| **Activation refused** (`409`, `coverage_fail` / `quality_below_floor`) | The `activation_gate` block and the Quality misses | Backfill the missing kinds; fix content/views/golden set; re-run compare. Both gates must pass. |
| **No golden set** (`no_golden_set`) | Quality section | Ship the versioned golden-query fixture for the space; activation cannot proceed without it. |
| **Stale run** (`retrieval.reindex_stalled`) | Run drawer heartbeat; Jobs & runs | Wait for the 15-minute reaper (it fails the run and releases the lock), or cancel; then retry. Check the worker is alive. |
| **Queued but nothing moves** | Audit → Jobs & runs; scheduler/worker health | Confirm the worker and `retrieval_alert_sweep` are running; cancel and retry if the row is wedged. |
| **Another run holds the space** (`409`) | Audit → Runs (queued/running for the space) | Wait for it, or cancel it, then retry. One active run per space is intentional. |
| **Idempotency replay mismatch** (`409`) | The key and body | Use a new key for a different request; replay the same key+body to read the original result. |
| **Budget exhausted** (`retrieval.budget_exhausted`) | Audit → Usage: embed tokens vs `AIBudget(task_type='embed')` | Wait for the next budget window or raise the embed budget; the per-run **Budget** field caps a single reindex separately. |
| **Degraded queries** (`retrieval.degraded_rate`) | Query health reasons | Fix the named cause (assignment, index, space mismatch, cap); lexical fallback is expected while degraded. |
| **403/404 on a surface** | Admin session | Retrieval is instance-admin only; the desktop owner is admin by first-user provisioning. |
| **Desktop: `database is locked` from `semantic_rescue`** | Backend log: `sqlite3.OperationalError: database is locked` at a `vector_documents` INSERT, ~30s after startup | The vector store commits through its own connection and SQLite has one writer; the inline index now releases the caller's transaction before indexing **and again after the embed** (the gateway audits by flushing an `ai_generations` row into the same session, which re-takes the lock) — plans 192/194. If it still appears, check for another long-running writer (an import or a raw `sqlite3` session) and restart. |

After any fix, re-run the smallest scoped action that proves it (one kind or
one view), read the run result, then widen the scope. Record the run id and
the audit event in the incident note; the Changes section already has the
`vector.*` trail.
