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
| `education_items`, `certifications`, `profile_achievements` | `profile_entities_model.py` | Education, certifications, achievements. A later revision replaces the qualitative `grade_band` with the scale-scoped `grade_scale` + `grade_value` + derived `grade_ordinal` (UK honours, 4.0/10 GPA, German Note, percentage; never cross-converted) |
| `saved_answers` | `profile_entities_model.py` | One user-written screening answer per `question_key` (unique per user), with `question_text`, `answer_text` and typed `evidence_refs`; the kit is the reader |
| `interview_stories` | `interview_model.py` | One STAR story per user (title, competency tags, S/T/A/R, optional `experience_item_id`, typed evidence refs); practice prepends a story-derived behavioral question |
| `organizations` | `experience_model.py` | Normalized employers |
| `documents` | `document_model.py` | Uploaded files (CVs, admission PDFs) |

Skills and interests are **FK join tables**, never JSONB, so the taxonomy
stays referentially intact.

## Taxonomy and catalog

| Table(s) | Model | Holds |
|---|---|---|
| `interest_tags` | `taxonomy_model.py` | Interest vocabulary |
| `skills` | `taxonomy_model.py` | Skills ontology: key, label, category, subskills, level anchors, aliases, lifecycle |
| `skill_relations` | `taxonomy_model.py` | Typed skill↔skill edges (`is_a`, `synonym`, `part_of`, `related_to`) with review status (`proposed` → `approved` / `rejected` negative edge), provenance source, confidence, `evidence` JSONB; symmetric kinds stored canonically ordered (lower UUID in `from_skill_id`) |
| `job_families` | `job_model.py` | The family tree |
| `jobs` | `job_model.py` | Jobs with rich structured attributes |
| `job_relations` | `job_model.py` | Typed edges (`similar_to`, `specialises_into`, `leads_to`, `alternative_to`, `prerequisite_of`) with weight/rationale/source |
| `job_skills`, `job_tags` | `job_model.py` | FK joins to `skills` / `interest_tags` |
| `career_paths`, `career_path_steps` | `career_path_model.py` | Curated and AI-drafted routes; steps carry `parent_step_id` + `edge_label` for branching |
| `label_overrides` | `localization_model.py` | Review-first catalog i18n overlays (`entity_kind` + `entity_id` + `locale` + `field` unique; AI drafts land as `draft`, only approval reaches `approved`) |
| `user_path_flags` | `career_path_model.py` | A user's `interested`/`dismissed`/`pinned` mark on a path (`step_id` NULL = the whole path) |

`background_jobs.job_type` is the second pre-existing §6 exception (a plain
string column, absent from `test_schema_contracts.CHECKS`).

`jobs.status` carries the closed vocabulary `draft | published | retired`
(`JobStatus`). `retired` is written only by the job-type merge service:
a duplicate type is retired into its survivor, never deleted,
and the row keeps `ai_metadata.retired_into` / `retired_at` /
`retired_reason` as the trail. The column is a **pre-existing §6 exception**
(plain `String(20)`, no mirrored CHECK, absent from
`test_schema_contracts.CHECKS`), so the additive enum member needs no DDL;
the debt is recorded here, not widened.

`jobs.title_key` is the derived normalized title
(`String(200)`, `ix_jobs_title_key`), written by the `before_insert` /
`before_update` SQLAlchemy event on every ORM write, including the seed.
The write-path guard compares it across non-retired rows; migration `0003`
backfills existing rows. The index is deliberately **not unique** while live
duplicate pairs exist — the partial unique index is a
follow-up, not current schema.

`skill_relations` is the typed edge table over `skills`:`from_skill_id`/`to_skill_id` (FK `skills.id` CASCADE, each indexed),
`relation` (`is_a | synonym | part_of | related_to`, CHECK
`relation_allowed`), `status` (`proposed | approved | rejected`, CHECK
`status_allowed`), `source` (`llm | manual | import | derived`, CHECK
`source_allowed`), nullable `confidence` (CHECK `confidence_range` 0–1 —
NULL = "not scored", never fabricated), `evidence` JSONB, and
`decided_by`/`decided_at` for the review queue. **Lifecycle:** `proposed
→ approved | rejected`, where `rejected` is the **negative edge** ("never
this pair + relation") — it permanently blocks the suggestion from
returning, it is not a tombstone. `UNIQUE(from_skill_id, to_skill_id,
relation)` (`uq_skill_relation_edge`) dedups per (pair, relation);
`no_self_loop` forbids self-edges; `symmetric_pair_ordered` stores the
symmetric kinds (`synonym`, `related_to`) with the lower UUID in
`from_skill_id` so one unordered pair can never carry two rows (directed
kinds keep their direction). **`evidence` is write-once**: a later
suggestion refreshes `confidence` but never overwrites the first
provenance.

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
| `job_sources` | `posting_model.py` | Configured connector sources: `kind` (`posting`/`market`/`university`/`search`/`webhook_in`), `title` (optional display name from the extension manifest), `schedule_kind`, `paused_at`, `last_status` (`ok`/`degraded`/`failed`) |
| `job_postings` | `posting_model.py` | Live postings + extraction payload; the typed mapping-truth columns `mapping_margin` (weak-review margin), `extract_status` (`succeeded`/`failed`) and `proposal_proposed_at` (typed v2 proposal time). `language_codes` holds the comma-delimited projection (`",en,el,"`) of the structured `extract.language_requirements` rows used by the Explore facet; the structured rows carry code, level and evidence — plus the eligibility columns `work_authorization`, `opportunity_type` and `application_deadline`; the trust columns `duplicate_of_id` (self-FK, NULL = canonical, clear = undo), `repost_count`, `last_verified_at` and the typed `trust_flags` JSONB (duplicate proposals) |
| `posting_skills` | `posting_model.py` | Extracted skills with level/priority/evidence |
| `posting_interactions` | `posting_model.py` | Engagement state only: seen / saved / hidden; `gate_overrides` (`{"visa": true}`) — the per-user "apply anyway" map read fresh on every fit read, never part of the fit cache hash |
| `applications` | `application_model.py` | The application pipeline, 1:1 per user+posting: `stage`, `applied_at`, `applied_via` + `applied_via_url`, `deadline_at`, `next_followup_at`, `contact_id` (the structured contact), `offer` (`{currency, amount, period, benefits[]}` — money triple), `outcome`/`closed_at`, `cv_id`/`cover_letter_id`, `external_ref`, `notes`, extension-only `meta` |
| `contacts` | `contact_model.py` | One flat user-owned person around applications (`name`, `org`, `role`, `email`, normalized nullable `email_key` with a per-user partial unique index, `profile_url`, `notes`, `tags`, derived `last_contacted_at`, `source`); no cadence and no enrichment |
| `contact_interactions` | `contact_model.py` | One logged outreach moment (`kind`, `at`, `channel`, `notes`, optional `application_id`); contact delete cascades, application delete sets null |
| `application_events` | `application_model.py` | Append-only timeline: `at`, `kind`, `stage_from`/`stage_to`, `body`, `actor`, per-kind `meta` (`document_id` for `document_linked`, `step` for `followup_*`, `scheduled_at` + optional `duration_minutes` for `interview_scheduled`, plus ICS `ics_uid`/`all_day`/`end`/`location` on imports, the webhook payload for `external_update`); every stage transition writes exactly one `stage_change` |
| `followup_rules` | `followup_model.py` | Per-user follow-up cadence (`cadence_days`), milestone check-ins, per-kind channel routing (`default`/`followup_due`/`interview_checkin`/`offer_checkin`) |
| `user_feed_tokens` | `followup_model.py` | Hashed `.ics`/RSS subscription tokens (`kind` = `ics`/`rss`): `scope` is `{}` (everything) or `{"saved_search_id": …}` for RSS, plaintext shown once at mint/rotation, `last_used_at`, `revoked_at` + `rotated_from_id` chain |
| `webhook_endpoints` | `posting_model.py` | Inbound-webhook keys (`target` = `posting_status`/`application_status`/`ingest`), hashed token, health |
| `posting_fits` | `posting_model.py` | Per-posting fit + `inputs_hash` staleness, `computed_at` and `fit_version` for bounded recompute/trends |
| `market_snapshots` | `market_model.py` | Aggregated market data |
| `autopilot_goals`, `autopilot_runs`, `autopilot_findings` | `autopilot_model.py` | Goals, runs (with the durable `run_steps` step trace) and explainable findings |

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

**Mapping-truth columns.** `job_postings.mapping_margin` is the
skill-ranked top-minus-second margin of a deterministic mapping (0..1,
CHECK-enforced; NULL for manual/semantic; pre-existing rows stay NULL until
the owner runs the re-decide sweep, while new deterministic mappings write it
immediately). `extract_status` records the extract attempt outcome
(`succeeded`/`failed`, CHECK-enforced; NULL for never-attempted rows) and is
written by the extract paths in S3. `proposal_proposed_at` is the typed v2
proposal timestamp written by `store_job_type_proposal` and cleared by
dismiss/clear/map; the queue display and `mapping_ops` aging read the typed
column, with `created_at` as the fallback for rows the migration could not
parse. The three indexes are `ix_postings_mapping_margin`,
`ix_postings_proposal_proposed_at` and `ix_postings_status_extract`.
`job_postings.mapping_features` is schema version 2 / mapping version 3 for
new decisions (v1 rows still parse); the payload carries the deterministic/
semantic/blend legs, shared taxonomy keys and the title evidence. Automatic
semantic writes are re-decided by the scoped `POSTING_REMAP` backfill; manual
rows are never overwritten.


## Economic context

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
| `extension_sources` | `extension_model.py` | Git sources (https production + dev/test `local` variant) and operator-feeder sources (`mount_key`/`mount_path` provenance): validated descriptor, sealed credential slots, discovery candidates, family status vocabulary |
| `extension_installs` | `extension_model.py` | Digest-pinned imported extensions: manifest, pin ref + history, consent records (who/when/what-digest), update state, lifecycle state, the minted `job_sources` key |

Imported content itself is data on disk — content-addressed under
`data_dir/extensions/<id>/<digest>/` — never a table row, never
importlib'd (D2). The GitOps desired-state document lives in
`app_settings` under `extensions.desired_state` (admin-owned; validated
against the vendored `desiredStateDocument` schema, which cannot express
deletion).

## Seed providers and the source catalog

| Table(s) | Model | Holds |
|---|---|---|
| `seed_sources`, `seed_source_versions` | `seed_model.py` | Providers (file upload/registry index/public git) and their immutable, content-addressed pack versions. `scope` is `system` only; `current_version_id` is the *applied* pointer (circular FK with the version's `source_id`, `use_alter`, `SET NULL`). Approval is exact-digest; sync never applies. |
| `seed_sync_runs`, `seed_import_runs`, `seed_import_run_items` | `seed_model.py` | The fetch ledger (trigger/status/etag/commit/bytes), the planner/applier run ledger, and one row per `seed_key` decision (create/update/noop/conflict/skip/override/retire) |
| `seed_item_provenance`, `seed_deferred_refs` | `seed_model.py` | Read-only per-entity origin projection and unresolved references retried on the next approval |
| `job_source_presets`, `provider_endpoints` | `seed_model.py` | The applied catalog — ATS/remote presets and endpoint descriptors, unique `(scope_key, seed_key)` with the uuid5 identity. `state` (active/retired/overridden) is the liveness authority; `job_sources.key` stays the slug. |
| `provider_subscriptions`, `source_prefs` | `seed_model.py` | User-scoped follow/hide overlays (`hidden` is the hard deny applied before every other filter); a subscription never creates a `job_sources` row |
| `migration_archive` | `seed_model.py` | Exact pre-fold value kept by a self-contained data migration |

Pack content is data, never code. `job_sources` gains the nullable
`seed_source_id` / `seed_item_key` / `applied_version_id` provenance pointers
and `support_status` (`supported|retired`); retiring a preset never deletes
the source row. `schedules.kind`/`task` carry `system_provider_sync` /
`provider_sync` as of `0018`.

`0019` is a self-contained data fold: it reads the legacy
`app_settings['posting.sources.catalogs']` blob, synthesizes an approved
`file` provider per catalog at priority 90, writes the preset/endpoint rows
and provenance, and archives the exact v1 blob plus the synthesized pack
files in `migration_archive`. Invalid catalogs are stored as `rejected`
(the upgrade never aborts); the downgrade restores the original setting.

### Migration notes

The chain is a **single no-BC baseline** (`0001_baseline_schema.py`) since
v0.17: the earlier `0001` and the `0002`–`0100` revisions were replaced by
one schema generated from the final models. v0.16.0 → v0.17 is a declared
breaking release with no production users, so the baseline's empty-schema
`downgrade()` is an approved one-off (declared in the revision header) —
recreate dev/test databases instead of downgrading. The pre-baseline notes
are archived in git history and no longer describe files in the tree.

Because the baseline is model-generated, the tables above are the whole
truth. The one DATA row set it seeds outside table defaults is the company
quality denylist (`organization_match_exclusions`, 18 editable rows, formerly
revision `0070`). `tests/test_migrations.py` pins the single head, the fresh
SQLite upgrade → downgrade → upgrade round-trip, the denylist seed and the
model ⇄ baseline drift check.

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
| `embedding_model_profiles` | `embedding_profile_model.py` | Admin tokenizer/limit override per provider-class + model: tokenizer kind/identifier/revision/checksum/exact, max input tokens, per-request batch item/token limits and the default token `ChunkConfig` preview. Kinds are `tiktoken`, `hf_tokenizers` and `heuristic`; `sentencepiece` is reserved. Curated rows live in code (`app/ai/tokenizers/registry.py`) with HF provenance (repo/revision/SHA-256/license/source URL); the resolver order is admin → curated → conservative fallback, keyed on `(provider_class, model_name)` — never a model-name substring. A row is configuration, not a chunk/space rewrite. Fetched HF artifacts are cached at `<data_dir>/tokenizers/<sha256>/tokenizer.json`, not in the database |
| `ai_generations` | `ai_model.py` | The AI audit ledger (task, model, tokens, output, latency, run linkage) plus the caller-supplied retrieval tags (`metadata` + `metadata_schema_version` — space/kind/view/chunk index only, never text). Call-time cost provenance: `cost_micros`, `usage_source` (`provider`/`estimated`/`partial`/`unknown`), `estimate_method`, `price_source` (`user`/`builtin`/`local`/`unknown`) and `price_version`; an unknown price stays NULL, never zero |
| `ai_price_overrides` | `ai_model.py` | System-scoped price rows (provider preset key or product `provider_ref`, model, `exact`/`prefix` match, input/output micros per million, `tokens`/`input_only`/`output_only` metering). Read/write through the admin-only `/ai/prices` surface; the resolver order is user row → override → built-in list price → local zero → unknown |
| `ai_budgets` | `ai_model.py` | Budget tracking |
| `ai_skill_packs` | `skill_pack_model.py` | Versioned instruction data |
| `vector_spaces`, `vector_documents`, `vector_records` | `vector_model.py` | The family vector store: versioned embedding spaces (each row persists its `space_key` cutover identity, stamped once and compared verbatim by activation/remap/status), polymorphic source documents (kind + `source_id` + scope), and one record per view/chunk with a content hash, a `text_ref` pointer and — only under the linear backend — the vector BLOB. A token-aware space also persists its pinned tokenizer (kind/identifier/revision/artifact sha/exact/max input tokens/source provenance) and `ChunkConfig` scalars, with `chunker_version='2'`; legacy rows keep every tokenizer/chunk column NULL and the frozen v1 key. Records carry nullable `token_count`/`token_start`/`token_end` when token-chunked (NULL on legacy char chunks; `token_count == token_end - token_start`). The physical per-space index (`vec_*`, HNSW or `vec0`) is provisioned by a job/migration, never Alembic |
| `retrieval_query_rollups`, `retrieval_coverage_snapshots` | `vector_model.py` | Bounded operational telemetry (first written by the reconcile pass): query-health buckets and per-kind coverage points (`total`/`missing`/`stale`/`failed`/`embedded` + the sampled ANN recall) |
| `ai_mcp_servers` | `mcp_bridge_model.py` | External MCP server registrations |
| `mcp_tokens` | `mcp_bridge_model.py` | Hashed MCP access tokens (personal or instance-wide), closed `scopes`, rotation + per-token revocation |

## Growth, engagement and notifications

| Table(s) | Model | Holds |
|---|---|---|
| `growth_plans`, `growth_plan_steps` | `growth_model.py` | Roadmaps |
| `learning_resources` | `growth_model.py` | Resources for skill gaps |
| `search_history` | `engagement_model.py` | Saved/recent searches |
| `smart_query_cache` | `smart_search_model.py` | Cross-user NL-search cache: `query_hash` PK = sha256 of the normalized query, closed `SmartSearchSpec` JSONB, `created_at`. TTL-pruned (7 days) by the daily smart-digest job — cache data, never a record |
| `notifications`, `notification_recipients`, `notification_deliveries` | `engagement_model.py` | The notification funnel (dedup keys, delivery state); `channel` spans `in_app`/`desktop`/`browser`/`email`/`webhook`. A `pending` delivery with `error = deferred:<quiet_hours|digest_mode>` is email waiting for the next digest run; webhook rows stay `pending` until the queued delivery job reports |
| `user_channel_configs` | `engagement_model.py` | Per-user, per-channel config — email: `address` override, `digest_mode`, `pending_address`/`verification_hash`/`verification_expires_at` while double opt-in is open; webhook: `url` + `template` (`generic`/`slack`/`teams`/`telegram`/`ntfy`) — sealed `secrets` (webhook token only; URLs are not secrets) + `verified_at` |
| `notification_kinds`, `notification_kind_prefs`, `notification_rules`, `notification_preferences`, `notification_subscriptions` | `engagement_model.py` | Kind registry, per-rule caps/cooldowns, quiet hours |

## Scheduling and operations

| Table(s) | Model | Holds |
|---|---|---|
| `background_jobs` | `background_job_model.py` | The job queue (status, result, run linkage) plus the nullable `idempotency_key`/`lock_key` handles and their active-status partial unique indexes and the bounded live `progress_detail` counters. `tokenizer_fetch` rows are plain jobs: they are not `VECTOR_*` runs and never take a space lock |
| `schedules` | `schedule_model.py` | Trigger definitions, misfire policy, claimed/queued state |
| `app_settings` | `settings_model.py` | Instance settings (AI config, web tools, notification config) |
| `interview_sessions` | `interview_model.py` | Interview plans, rubric aggregates, status |

## Related

- [Architecture](architecture.md) — how these fit together at runtime
- [Migrations](migrations.md) — changing the schema
- [AI layer](ai-layer.md) — the `ai_*` tables in context
