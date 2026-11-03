# Scheduler and jobs

Two registries own all periodic work and all notifications. The scheduler
decides **when** and only enqueues jobs; the job worker does the work; the
notification funnel decides **how you are told**.

## Background jobs

`app/services/job_worker.py` drains the `background_jobs` table. Each job has
a type (`BackgroundJobType`) and a handler in the `HANDLERS` map:

| Job type | Handler |
|---|---|
| `document_parse` | Parse an uploaded document |
| `job_generate` / `path_suggest` / `catalog_enrich` | Catalog AI work |
| `match_score` / `fit_refit` | Scoring and re-fit sweeps |
| `posting_sync` / `posting_extract` | Connector sync + deep extraction |
| `saved_search_run` / `autopilot_run` | Saved searches and Autopilot |
| `cv_extract_text` / `cv_ocr` / `cv_parse` | CV intake pipeline |
| `cv_generate` / `cv_polish` / `cv_synth` | CV generation, polish loop, variants |
| `digest` / `followup_sweep` | Digests and application follow-ups |
| `market_history_capture` / `proposal_sweep` / `checkpoint_prune` | Maintenance sweeps |
| `skill_relation_learn` | Skill-relation edge discovery + tree catch-up (plan 138): propose typed edges from evidence, and fill empty `parent_id` from approved `is_a` rows (reported as `backfilled` on the run ledger) |
| `vector_index` / `vector_reconcile` | Index one document / backfill and reconcile the family vector store (plan 50) |
| `posting_remap` | Re-decide semantic catalog mappings after a space cutover (plan 50 P2b) |
| `data_export` | Exports |

The plan-138 learn job is the one handler that lives in the catalog —
`app/services/catalog/skill_relation_learn.py`, reached through the
`HANDLERS` entry in `job_worker.py`. What it does: **candidates → batched
LLM verdicts (≤40 pairs/call) → `proposed` edges through the one write
seam → parent backfill** (empty `parent_id` filled from approved `is_a`
rows). Its run ledger on `background_jobs.result` reports `candidates,
batches, judged_batches, failed_batches, uncovered, derived,
edges_proposed, negatives, dropped, below_bar, materialized, backfilled,
capped, watermark` — a capped/failed/unconfigured run keeps the previous
watermark floor (`null` before any success). Thresholds live in one
AppSetting, `skill_relation_learn.thresholds` (`min_support`,
`batch_size`, `max_pairs_per_run`, `min_negative_confidence`), edited via
`GET/PUT /admin/skill-relations/thresholds`. Its system schedule is
boot-provisioned like every system kind (no seeded migration row).

Jobs run as FastAPI background tasks (`CAREER_JOBS_WORKERS`); Redis ships in the
compose file for a later worker split — there is no Celery in v1.

### The deep extract re-decides the catalog mapping (plan 185)

The `posting_extract` job's contract is unchanged (one structured call +
apply), but its transaction now carries the **catalog join** too: after
`apply_extract` fills the skill levels, `decide_catalog` re-runs the mapping
join — the deterministic weighted skill overlap first, then the gated
semantic rescue on the family vector store
([ai-layer.md](ai-layer.md#the-hybrid-catalog-mapping-plan-185)) — and an
unmapped-and-rich extract stores a `job_proposal` for the admin queue.
A `MANUAL` mapping stands. Plan-184 interplay: requeued `posting_extract`
jobs re-run this join through the same handler — a bulk reprocess can
therefore upgrade mappings and mint fresh proposals; the proposal writer
never clobbers a live pending proposal.

### The vector reconcile (plan 50 P1d)

`system_vector_reconcile` enqueues a `vector_reconcile` job daily (04:15
UTC) for `posting`, `job`, `profile` and `skill`. The handler composes sources
of the selected kinds and compares the
composed hash with the stored document: unchanged content costs zero
embedding calls, missing/stale documents are indexed through the same writer
the `VECTOR_INDEX` job uses. The scan is a **bounded keyset batch** —
`scan_limit` source rows per kind, read with an exclusive `(updated_at, id)`
cursor — so a run never loads or composes the whole corpus. Sources are
processed one at a time; no all-dirty work list is held.

Two caps still bound a run — `limit` (documents) and `budget` (embed units).
When a cap is hit mid-batch the run stops before the next source and returns
`next_after` (the last fully processed source), `carry` (cumulative counters)
and `completed_kinds`. The handler enqueues one follow-up `vector_reconcile`
with that state unless `auto_continue` is false; the same
`(space, kind, cursor)` continuation is never duplicated, and a cancelled run
never chains. A kind writes its `retrieval_coverage_snapshots` row only when
its scan is complete for the chain, so a partial batch never publishes a
misleading full-coverage point; counters carried across the chain make a
resumed completion describe the whole kind.

Deleting a source row orphans its document. Only a full, unwindowed pass
(`done=true`, no `since`) sweeps orphans, and it inspects at most
`scan_limit` documents per pass rather than loading the whole table. Embed
spend goes through the gateway's **system** path (no admin's personal budget
is charged); `POST /api/v1/admin/retrieval/reconcile` and
`scripts/reindex_vectors.py` only enqueue the job (both accept `scan_limit`),
so every run is a `background_jobs` row. Publishing or editing a catalog job
queues a `VECTOR_INDEX` for it rather than embedding in the request. The full
Runs/Retrieval surface is plan 51.

### The posting remap after a space cutover (plan 50 P2b)

A semantic mapping depends on the embedding space it was decided in:
`job_postings.mapping_features` stamps the contract's `space_key`. When a
space is retired/cut over, `app/services/postings/mapping_remap.py` is the
single invalidation seam — `invalidate_mapping_space(space_key=retired.key)`
enqueues a bounded `POSTING_REMAP` job. The handler selects only
`mapping_method IN ('semantic','semantic_rerank')` rows (never `manual`),
skips terminal statuses, re-runs `decide_catalog` without touching
`PostingSkill` rows, and pages by posting id with one auto-continuation
cursor. Plan 51's retrieval-management action calls the hook after the new
space is active; there is deliberately no second sweep. The run result
carries `{remapped, failed, skipped, next_after_id, space_key}`.

### The failed-jobs lifecycle (plan 184)

A job retries within its `max_attempts` budget (backoff between attempts);
once the budget is exhausted it lands `failed` **terminally** — the row is
audit history and its status is never mutated back into the queue. Recovery
is the admin audit console's **Failures tab** (`?tab=failures` on
`/settings/audit`): `JobReprocessService` previews the failed jobs grouped
by type × error family, then requeues them as FRESH `background_jobs` rows
(`requeue_of` marker back to the failed row, `result.requeued_as` on it)
through the same `HANDLERS` path with a fresh attempts budget. Guards and
the per-type policy (payload-driven per-job vs collapsing global sweeps)
are documented in [ai-layer.md](ai-layer.md#bulk-reprocessing-of-failed-jobs-plan-184).

## The scheduler

`app/services/scheduler/` — the runner (`runner.py`) and the trigger registry
(`triggers.py`). On boot the runner seeds system schedules (source sync,
re-fit sweep, catalog enrich, follow-ups, market history, proposal sweep,
checkpoint prune, skill-relation learning) with defaults and jitter.

### Triggers

Triggers are a registry (entry-point group
`career_assistant.scheduler_triggers`). Built-ins:

| Trigger | Fires |
|---|---|
| `IntervalTrigger` | Every N minutes, with optional jitter |
| `DailyAtTrigger` | At a local time each day |
| `WeeklyTrigger` | On selected weekdays at a time |
| `CronTrigger` | A cron expression |
| `BootStaleTrigger` | When data is stale at boot (catch-up) |

Each trigger validates its params (pydantic) and computes `next_after(now,
params)` — always timezone-aware and UTC-normalized.

### Schedule kinds

`ScheduleKind` covers both system and user schedules: `system_source_sync`,
`system_digest`, `system_demand_import`, `system_refit_sweep`,
`system_catalog_enrich`, `system_followups`, `system_market_history`,
`system_proposal_sweep`, `system_checkpoint_prune`,
`system_extension_reconcile`, `system_skill_relation_learn` (daily at
03:30 UTC — enqueues `skill_relation_learn`), `user_saved_search`,
`user_radar_digest`, `user_checkin`, `user_autopilot`. `runner.py` maps each kind to a job type;
`system_demand_import` enqueues `demand_import`, which walks enabled
`job_sources` rows of kind `market` and writes salary/outlook observations
into `market_snapshots` and `jobs.demand` (field-level provenance).

### Ticking and misfires

`SchedulerService(db).tick()` claims due schedules and enqueues their jobs
(status `claimed` → `queued`, or `skipped_overlap` / `skipped_misfire`). The
**misfire policy** (`asap`, `skip`, `next_slot`) decides what happens when a
run is late — for example after the desktop sleeps. Exponential backoff marks
a stuck schedule.

**Tests never run the live loop** (`CAREER_SCHEDULER_ENABLED=false`); call `tick()`
directly. See [testing.md](testing.md).

## The notification funnel

`app/services/notification_service.py` — `NotificationService.emit` is the
**single funnel**: it writes the event + inbox rows, then dispatches per
channel. Nothing else should send notifications.

- **Dedup**: `dedup_key` + `dedup_expires_at` collapse duplicate emits; a
  suppressed emit returns `None`.
- **Kinds**: `notification_kinds` is the kind registry; a disabled kind never
  reaches a channel.
- **Guardrails**: per-rule caps, cooldowns and quiet hours are applied per
  recipient before transport.
- **Channels**: `notification_channels.py` + `available_channels()` /
  `get_channel()`; `NOTIFICATION_CHANNELS_ALLOWLIST` gates plugin channels.
  Desktop native toasts are a channel.

Alert rules and their triggers live on `EngagementService`; the follow-up
sweep and threshold alerts both emit through this funnel.

## Related

- [Architecture](architecture.md) — where the scheduler fits
- [Data model](data-model.md) — `background_jobs`, `schedules`, notification tables
- [User: Notifications and scheduler](../user/notifications-and-scheduler.md)
- [Adding features](adding-features.md#add-a-scheduler-trigger)
