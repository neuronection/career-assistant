# Data model

The schema is **dialect-aware**: one Alembic chain runs on PostgreSQL
(web/self-host, JSONB) and SQLite (desktop). Typed columns hold anything the
app queries or constrains; JSONB holds structured, schema-validated
documents. Every JSONB write is validated by pydantic on the way in.

## Dialect rules

- **Postgres is the default; SQLite must be verified.** A migration or query
  that works on one and not the other is a bug. Use the portable column types
  from `app/models/base.py` and per-dialect branches only where unavoidable.
- **JSONB is a document, not a query surface.** If the app filters or sorts on
  it, promote it to a typed column. `flag_modified(obj, "field")` is required
  before committing a JSONB mutation.
- **Sequential Alembic revision ids** (`0001`…; file names add a slug). See
  [migrations.md](migrations.md).

## Identity and profile

| Table(s) | Model | Holds |
|---|---|---|
| `users` | `user_model.py` | Accounts (family-normative `users`, identity-auth §5); `locale` is the optional UI locale (NULL = the instance default) |
| `profiles` | `user_model.py` | The structured profile document — family 1:N per user (`name`, `is_default`, `last_used_at`, `preferences` + career's JSON sections; §5/§6) |
| `auth_sessions` | `identity_model.py` | Refresh families (rotation + reuse detection, §5) |
| `instance_settings` | `identity_model.py` | Instance access-mode facts (`auth_mode`, `demo_mode` — init-only, §4) |
| `audit_events` | `identity_model.py` | Append-only auth/admin audit trail (§5) |
| `user_interests` | `user_model.py` | FK join to `interest_tags` (never JSONB) |
| `user_skills` | `user_model.py` | FK join to `skills`, with level |
| `experience_items`, `experience_skills`, `experience_achievements` | `experience_model.py` | Jobs, internships, freelance, projects, volunteering + their links |
| `skill_evidence` | `experience_model.py` | Evidence backing a skill level |
| `education_items`, `certifications`, `profile_achievements` | `profile_entities_model.py` | Education, certifications, achievements |
| `organizations` | `experience_model.py` | Normalized employers |
| `documents` | `document_model.py` | Uploaded files (CVs, admission PDFs) |

Skills and interests are **FK join tables**, never JSONB, so the taxonomy
stays referentially intact.

## Taxonomy and catalog

| Table(s) | Model | Holds |
|---|---|---|
| `interest_tags` | `taxonomy_model.py` | Interest vocabulary |
| `skills` | `taxonomy_model.py` | Skills ontology: key, label, category, subskills, level anchors, aliases, lifecycle |
| `job_families` | `job_model.py` | The family tree |
| `jobs` | `job_model.py` | Jobs with rich structured attributes |
| `job_relations` | `job_model.py` | Typed edges (`similar_to`, `specialises_into`, `leads_to`, `alternative_to`, `prerequisite_of`) with weight/rationale/source |
| `job_skills`, `job_tags` | `job_model.py` | FK joins to `skills` / `interest_tags` |
| `career_paths`, `career_path_steps` | `career_path_model.py` | Curated and AI-drafted routes; steps carry `parent_step_id` + `edge_label` for branching |
| `label_overrides` | `localization_model.py` | Review-first catalog i18n overlays (`entity_kind` + `entity_id` + `locale` + `field` unique; AI drafts land as `draft`, only approval reaches `approved`) |
| `user_path_flags` | `career_path_model.py` | A user's `interested`/`dismissed`/`pinned` mark on a path (`step_id` NULL = the whole path) |

## Universities

| Table(s) | Model | Holds |
|---|---|---|
| `universities`, `departments`, `department_admissions` | `university_model.py` | Institutions, departments and yearly admission baselines |
| `job_department_links` | `university_model.py` | Rich degree→job link rows (relevance, subjects, salary band, employment rate) |

## Matching and metrics

| Table(s) | Model | Holds |
|---|---|---|
| `match_insights` | `matching_model.py` | AI score + structured rationale (positives, negatives, missing prerequisites) |
| `metric_dimensions` | `metric_model.py` | The curated dimension registry |
| `user_metric_profile` | `metric_model.py` | Measured values with provenance |
| `skill_transferability` | `metric_model.py` | Per-skill transferability across families |
| `assessment_templates` | `assessment_template_model.py` | Bank batteries |
| `assessment_runs`, `assessment_questions`, `assessment_answers` | `assessment_model.py` | Resumable assessment runs |

## Postings and market

| Table(s) | Model | Holds |
|---|---|---|
| `job_sources` | `posting_model.py` | Configured connector sources: `kind` (`posting`/`market`/`university`/`search`/`webhook_in`), `schedule_kind`, `paused_at`, `last_status` (`ok`/`degraded`/`failed`) |
| `job_postings` | `posting_model.py` | Live postings + extraction payload |
| `posting_skills` | `posting_model.py` | Extracted skills with level/priority/evidence |
| `posting_interactions` | `posting_model.py` | Engagement state only: seen / saved / hidden |
| `applications` | `application_model.py` | The application pipeline, 1:1 per user+posting: `stage`, `applied_at`, `applied_via` + `applied_via_url`, `deadline_at`, `next_followup_at`, `contact` (`{name, email, role, channel}`), `offer` (`{currency, amount, period, benefits[]}` — money triple), `outcome`/`closed_at`, `cv_id`/`cover_letter_id`, `external_ref`, `notes`, extension-only `meta` |
| `application_events` | `application_model.py` | Append-only timeline: `at`, `kind`, `stage_from`/`stage_to`, `body`, `actor`, per-kind `meta` (`document_id` for `document_linked`, `step` for `followup_*`, `scheduled_at` + optional `duration_minutes` for `interview_scheduled`, the webhook payload for `external_update`); every stage transition writes exactly one `stage_change` |
| `followup_rules` | `followup_model.py` | Per-user follow-up cadence (`cadence_days`), milestone check-ins, per-kind channel routing (`default`/`followup_due`/`interview_checkin`/`offer_checkin`) |
| `user_feed_tokens` | `followup_model.py` | Hashed `.ics`/RSS subscription tokens (`kind` = `ics`/`rss`): `scope` is `{}` (everything) or `{"saved_search_id": …}` for RSS, plaintext shown once at mint/rotation, `last_used_at`, `revoked_at` + `rotated_from_id` chain |
| `webhook_endpoints` | `posting_model.py` | Inbound-webhook keys (`target` = `posting_status`/`application_status`/`ingest`), hashed token, health |
| `posting_fits` | `posting_model.py` | Per-posting fit + `inputs_hash` staleness, `computed_at` and `fit_version` for bounded recompute/trends |
| `market_snapshots` | `market_model.py` | Aggregated market data |
| `autopilot_goals`, `autopilot_runs`, `autopilot_findings` | `autopilot_model.py` | Goals, runs and explainable findings |

**Application pipeline lifecycle.** `app/services/postings/applications_service.py`
is the only writer of both tables. Any stage move — forward, backward or
terminal — is allowed and writes exactly one `stage_change` event (a move
to the same stage writes nothing); closing with accepted / rejected /
withdrawn also moves the stage, while expired / ghosted close without
touching it, and a closed application refuses further moves. A note
appends one `note` event and updates the rolling `notes` column; a
document link writes `document_linked` with the document ids in `meta`.
`next_followup_at` is the scheduler-facing projection: the service
recomputes it from `followup_rules.cadence_days` on create, transition
and rule changes (due immediately at Interview/Offer while milestone
check-ins are on), the follow-up sweep rewrites it after each pass from
the notification history, and a snooze pins it explicitly.


## Economic context (plan 127)

| Table(s) | Model | Holds |
|---|---|---|
| `geo_regions`, `geo_region_aliases` | `econ_model.py` | Canonical region join keys (country → metro) and the profile-string resolution cache |
| `econ_packs` | `econ_model.py` | Dataset pack / live provider instance: version, dataset vintage, license class, coverage JSONB, manifest, status (`proposed → active → superseded`) |
| `econ_series` | `econ_model.py` | Dimensional series inside a pack (geo × category × metric, provider dims JSONB, coverage level, license class) |
| `econ_observations` | `econ_model.py` | Values per (series, period, revision) with the provenance tier (`official → extracted → derived → ai_estimated`) and the verbatim evidence span + source hash for harvested values |
| `code_crosswalks` | `econ_model.py` | Typed code-system mappings (dataset category → sector → occupation) with method/weight/confidence and review stamp |
| `exposure_scores` | `econ_model.py` | Occupation AI-exposure scores per method (ILO GenAI, O*NET tasks) with source license |
| `scenarios`, `scenario_points` | `econ_model.py` | Named falsifiable scenarios (thesis, assumptions, indicators, falsifiers) and p10/p50/p90 distribution points |
| `claims`, `claim_events` | `econ_model.py` | Thesis-dossier claims with status and their timeline |
| `econ_watchlist` | `econ_model.py` | Per-user watched geo/sector/series/indicator scopes |

`market_snapshots` stays posting-derived; this layer sits beside it.
Observations never hold computed aggregates (those are derived in
`app/services/econ/`), and no row here feeds the fit score.

## Extensions (import layer)

| Table(s) | Model | Holds |
|---|---|---|
| `extension_sources` | `extension_model.py` | Git sources (https production + dev/test `local` variant): validated descriptor, sealed credential slots, discovery candidates, family status vocabulary |
| `extension_installs` | `extension_model.py` | Digest-pinned imported extensions: manifest, pin ref + history, consent records (who/when/what-digest), update state, lifecycle state, the minted `job_sources` key |

Imported content itself is data on disk — content-addressed under
`data_dir/extensions/<id>/<digest>/` — never a table row, never
importlib'd (D2). The GitOps desired-state document lives in
`app_settings` under `extensions.desired_state` (admin-owned; validated
against the vendored `desiredStateDocument` schema, which cannot express
deletion).

### Migration notes

- **0056** — plan 129 phase 2: `job_postings` gains `salary_basis`
  (gross | net, NULL = the source never said — the CHECK admits only
  the two known values) and the annualized range
  `salary_normalized_min` / `_max` (posted amounts scaled to a year on
  their own basis — no FX, no gross/net conversion; unknown period ⇒
  NULL, never a guess). Data backfill annualizes every row with an
  amount + known period; existing rows keep `salary_basis` NULL. The
  Explore salary filter and salary sort now run on the normalized pair.
  Covered by `tests/test_migrations.py::test_0056_salary_normalization_backfill`
  and `tests/test_salary_normalization.py`.
- **0055** — plan 129 phase 1: `company_profiles`, the reviewed 1:1
  firmographics layer over `organizations` (company type, size band,
  HQ, founded year, industry tags, links, typed financial claims with
  per-claim source + as-of). Purely additive; `organization_id` is
  unique + CASCADE. `OrganizationService.merge` re-points a lone
  profile and refuses to merge two. Covered by
  `tests/test_migrations.py::test_0055_company_profiles_roundtrip` and
  `tests/test_companies.py`.
- **0054** — plan 127 §3.0 (113 design review `§1.J`): the economic-
  context foundation — `geo_regions`, `geo_region_aliases`, `econ_packs`,
  `econ_series`, `econ_observations`, `code_crosswalks`,
  `exposure_scores`, `scenarios`, `scenario_points`, `claims`,
  `claim_events`, `econ_watchlist`. Purely additive; every enum column
  carries its mirrored CHECK. The revision id is `0054` — the plan text
  said `0053_econ_context`, but that slot was taken by
  `0053_demand_import_task` (plan 122 phase 3). Covered by
  `tests/test_migrations.py::test_0054_econ_context_tables_roundtrip`,
  the enum↔CHECK wall (`tests/test_schema_contracts.py`) and
  `tests/test_econ_models.py`.

- **0053** — plan 122 phase 3: `schedules.task_allowed` gains
  `demand_import` (the dormant `system_demand_import` slot shipped its
  schedule kind in 0051 but never its task value). No table/column/index
  changes. `downgrade()` deletes demand-import schedules (the old CHECK
  cannot represent them) and restores the previous text. Covered by
  `tests/test_migrations.py::test_0053_demand_import_task_check_roundtrip`.

- **0052** — plan 113 clean break: every `posting_interactions` row that
  carries application state (`applied_at`, `stage`, `notes`,
  `applied_via_url`) is folded into `applications` — one row per
  user+posting, `applied_via` `url`, an out-of-vocabulary legacy stage
  coerced to `applied` — and the four columns are dropped; dead
  `chat_title` background-job rows are deleted. `downgrade()` recreates
  the columns and folds the values back per user+posting (lossy only for
  applications that never had an engagement row, and for the deleted job
  rows) while **keeping the 0051 application tables**, which 0051's own
  downgrade then drops. Covered by
  `tests/test_migrations.py::test_0052_application_fold_and_downgrade_roundtrip`.

- **0051** — plan 113 additive foundation: new `applications`,
  `application_events`, `followup_rules`, `user_feed_tokens`,
  `user_channel_configs`, `webhook_endpoints`, `label_overrides`,
  `mcp_tokens`, `user_path_flags`; new columns `job_sources.kind` /
  `schedule_kind` / `paused_at` / `last_status`, `users.locale`,
  `profile_proposals.origin` (with `source` widened to 16),
  `career_path_steps.parent_step_id` / `edge_label`,
  `posting_fits.computed_at` / `fit_version`; `notification_deliveries.channel`
  widened for email/webhook. Existing `posting_fits` rows backfill
  `computed_at = updated_at` and `fit_version = 5`. Downgrade drops all of
  it and restores the narrow CHECKs.

- **0049** — the T2 sandbox runner's store (plan 32 Phase 5 /
  ADR-0030 Python port): widens `extension_installs.tier` to carry `T2`
  (tier is provenance at install — an `extension.py` capability-RPC
  artifact), adds `extension_installs.extension_state` (the T2
  `state.*` seam home — extension-owned KV, quota'd by
  `limits.stateMaxBytes`, distinct from sync cursors) and creates
  `extension_sandbox_runs` (one row per spawned sandbox; outcome +
  capped reason; boot reconciliation closes host-restart orphans as
  `interrupted`). Downgrade drops the table + column and restores the
  two-tier CHECK — T2 installs cannot exist below 0049 (tier is
  check-constrained).

- **0048** — `extension_sources` + `extension_installs` (plan 32 Phase 3 /
  ADR-0040 D13+D22); widens the `schedules.kind`/`task` CHECKs for the
  `system_extension_reconcile` slot (`extension_reconcile` job, hourly ±
  jitter; boot reconcile rides the app lifespan). Downgrade drops both
  tables and the schedule rows — consent records are install-row data,
  deleted with them, never leaked back.

## CV Studio

| Table(s) | Model | Holds |
|---|---|---|
| `cv_documents` | `cv_model.py` | A CV: working content, context, design tokens, template ref |
| `cv_versions` | `cv_model.py` | Immutable versions (payloads, diffs, page counts) |
| `cv_templates` | `cv_template_model.py` | The versioned template bank |
| `cv_synth_items` | `cv_synth_model.py` | The variant library (typed source refs + content hashes) |
| `cv_parse_drafts`, `cv_intake_applied` | `cv_intake_model.py` | Intake drafts and the applied ledger |

## Chat, proposals and AI

| Table(s) | Model | Holds |
|---|---|---|
| `chat_sessions`, `chat_messages` | `chat_model.py` | Sessions, messages, turn metadata (tools/nodes traces) |
| `profile_proposals` | `profile_proposal_model.py` | HITL proposal cards (diff, snapshots, status, lineage); `source` spans `chat`/`mcp`/`autopilot`/`import`, `origin` carries `{tool, session, request_id}` provenance |
| `ai_providers` | `ai_provider_model.py` | Providers with `api_key_encrypted` (Fernet) + `preset_key` (§15 adoption stamp) |
| `ai_models`, `ai_task_assignments` | `ai_provider_model.py` | Models (`caps` §15 vocabulary, `decision_transport`) + per-task / capability-slot assignments |
| `ai_generations` | `ai_model.py` | The AI audit ledger (task, model, tokens, output, latency, run linkage) |
| `ai_budgets` | `ai_model.py` | Budget tracking |
| `ai_skill_packs` | `skill_pack_model.py` | Versioned instruction data |
| `ai_embeddings` | `embedding_model.py` | Packed JSONB vectors (single source of truth) |
| `ai_mcp_servers` | `mcp_bridge_model.py` | External MCP server registrations |
| `mcp_tokens` | `mcp_bridge_model.py` | Hashed MCP access tokens (personal or instance-wide), closed `scopes`, rotation + per-token revocation |

## Growth, engagement and notifications

| Table(s) | Model | Holds |
|---|---|---|
| `growth_plans`, `growth_plan_steps` | `growth_model.py` | Roadmaps |
| `learning_resources` | `growth_model.py` | Resources for skill gaps |
| `search_history` | `engagement_model.py` | Saved/recent searches |
| `notifications`, `notification_recipients`, `notification_deliveries` | `engagement_model.py` | The notification funnel (dedup keys, delivery state); `channel` spans `in_app`/`desktop`/`browser`/`email`/`webhook`. A `pending` delivery with `error = deferred:<quiet_hours|digest_mode>` is email waiting for the next digest run; webhook rows stay `pending` until the queued delivery job reports |
| `user_channel_configs` | `engagement_model.py` | Per-user, per-channel config — email: `address` override, `digest_mode`, `pending_address`/`verification_hash`/`verification_expires_at` while double opt-in is open; webhook: `url` + `template` (`generic`/`slack`/`teams`/`telegram`/`ntfy`) — sealed `secrets` (webhook token only; URLs are not secrets) + `verified_at` |
| `notification_kinds`, `notification_kind_prefs`, `notification_rules`, `notification_preferences`, `notification_subscriptions` | `engagement_model.py` | Kind registry, per-rule caps/cooldowns, quiet hours |

## Scheduling and operations

| Table(s) | Model | Holds |
|---|---|---|
| `background_jobs` | `background_job_model.py` | The job queue (status, result, run linkage) |
| `schedules` | `schedule_model.py` | Trigger definitions, misfire policy, claimed/queued state |
| `app_settings` | `settings_model.py` | Instance settings (AI config, web tools, notification config) |
| `interview_sessions` | `interview_model.py` | Interview plans, rubric aggregates, status |

## Related

- [Architecture](architecture.md) — how these fit together at runtime
- [Migrations](migrations.md) — changing the schema
- [AI layer](ai-layer.md) — the `ai_*` tables in context
