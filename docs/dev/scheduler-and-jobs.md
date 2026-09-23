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
| `data_export` | Exports |

Jobs run as FastAPI background tasks (`JOBS_WORKERS`); Redis ships in the
compose file for a later worker split — there is no Celery in v1.

## The scheduler

`app/services/scheduler/` — the runner (`runner.py`) and the trigger registry
(`triggers.py`). On boot the runner seeds system schedules (source sync,
re-fit sweep, catalog enrich, follow-ups, market history, proposal sweep,
checkpoint prune) with defaults and jitter.

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
`system_proposal_sweep`, `system_checkpoint_prune`, `user_saved_search`,
`user_checkin`, `user_autopilot`. `runner.py` maps each kind to a job type.

### Ticking and misfires

`SchedulerService(db).tick()` claims due schedules and enqueues their jobs
(status `claimed` → `queued`, or `skipped_overlap` / `skipped_misfire`). The
**misfire policy** (`asap`, `skip`, `next_slot`) decides what happens when a
run is late — for example after the desktop sleeps. Exponential backoff marks
a stuck schedule.

**Tests never run the live loop** (`SCHEDULER_ENABLED=false`); call `tick()`
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
