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
| `skill_relations` | `taxonomy_model.py` | Typed skill↔skill edges (`is_a`, `synonym`, `part_of`, `related_to`) with review status (`proposed` → `approved` / `rejected` negative edge), provenance source, confidence, `evidence` JSONB; symmetric kinds stored canonically ordered (lower UUID in `from_skill_id`) |
| `job_families` | `job_model.py` | The family tree |
| `jobs` | `job_model.py` | Jobs with rich structured attributes |
| `job_relations` | `job_model.py` | Typed edges (`similar_to`, `specialises_into`, `leads_to`, `alternative_to`, `prerequisite_of`) with weight/rationale/source |
| `job_skills`, `job_tags` | `job_model.py` | FK joins to `skills` / `interest_tags` |
| `career_paths`, `career_path_steps` | `career_path_model.py` | Curated and AI-drafted routes; steps carry `parent_step_id` + `edge_label` for branching |
| `label_overrides` | `localization_model.py` | Review-first catalog i18n overlays (`entity_kind` + `entity_id` + `locale` + `field` unique; AI drafts land as `draft`, only approval reaches `approved`) |
| `user_path_flags` | `career_path_model.py` | A user's `interested`/`dismissed`/`pinned` mark on a path (`step_id` NULL = the whole path) |

`skill_relations` (plan 138) is the typed edge table over `skills`:
`from_skill_id`/`to_skill_id` (FK `skills.id` CASCADE, each indexed),
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

- **0094** — plan 52 T2a: `embedding_model_profiles`, the admin
  tokenizer/limit registry. Keyed on `(provider_class, model_name)`
  (unique `uq_embedding_model_profiles_scope`), with typed scalar columns —
  no JSONB. Holds the tokenizer kind/identifier/revision/checksum/exact
  flag, `max_input_tokens`, `batch_max_items`/`batch_max_tokens`, the
  default `ChunkConfig` preview (`chunk_max_tokens`/`chunk_overlap_tokens`/
  `chunk_max_chars`), `source` (closed to `curated|admin|fallback`; this
  slice writes `admin`) and `updated_by` (FK `users.id` SET NULL). CHECKs
  mirror the contract floor (`chunk_max_tokens >= 32`,
  `chunk_overlap_tokens * 2 < chunk_max_tokens`, chunk fits input, positive
  limits). No seed rows: curated OpenAI profiles live in code so a migration
  never invents model facts. Downgrade drops the table; overrides are
  rebuildable configuration, and every change is already on
  `audit_events` as `vector.model.changed`.
- **0093** — plan 52 T4: `background_jobs.progress_detail` (`StructuredJSON`,
  nullable; `JSONB` on PostgreSQL). A bounded live counter document
  (phase, processed/total documents, cumulative/estimated chunks,
  embedded/skipped/failed, tokens, embed calls) written in the same
  per-document UPDATE as `progress`/`stage`; pruned when the final `result`
  commits. Nullable for every other job family; no index or backfill, and
  downgrade drops the column.
- **0090** — plan 51 Q1a: the retrieval-operations checkpoint. Adds
  `ai_generations.metadata` (`StructuredJSON`, `NOT NULL` default `'{}'`)
  and `ai_generations.metadata_schema_version` (`SMALLINT`, default 1) —
  the caller-supplied embedding tags (`space_id`/`kind`/`view`/
  `chunk_index`), written by the caller through the gateway call exactly
  like `run_id`/`run_stage`, never invented by the gateway. Adds
  `background_jobs.idempotency_key` and `background_jobs.lock_key`
  (nullable, ≤120 chars) with two partial unique indexes over
  `status IN ('queued','running')`: `(job_type, idempotency_key)` is the
  request-replay key and `lock_key` is the one-active-run-per-space lock.
  The two rollup stores already exist from `0087` and are not recreated.
  Downgrade drops the indexes and columns; the tags are derived audit
  metadata.
- **0089** — plan 50 P2b: `job_postings.mapping_version` (the plan-164
  decision stamp, default 0 on rows that predate v2) and
  `job_postings.mapping_features` (`StructuredJSON`, nullable) — the bounded,
  service-validated provenance payload for the deterministic/semantic mapping
  (top candidates, per-view scores, policy thresholds, embedding `space_key`,
  degraded reason). Two indexes (`ix_postings_mapping_version`,
  `ix_postings_mapping_method`) serve the `POSTING_REMAP` cutover sweep. No
  `mapping_dirty` column: this slice selects semantic rows by method +
  recorded space key. The downgrade drops both columns and indexes; the
  payload is derived audit data, rebuilt by re-deciding the postings.
- **0083** — plan 179: `smart_query_cache`, the cross-user NL-search
  cache (`query_hash` PK = sha256 of the normalized query — casefold +
  whitespace collapse, so keys are stable across users; closed
  `SmartSearchSpec` JSONB; `created_at`). Cache data, not records: the
  daily smart-digest job prunes rows older than 7 days (explicit,
  documented purge). The downgrade drops the table — rebuildable by
  definition.
- **0080** — plan 173: `job_sources.title`, the display name for imported
  sources (the extension manifest's root `title` — "LinkedIn", not the
  generic connector label). Nullable: builtin sources keep NULL and fall
  back to the connector title at read time; managed imports seed the
  title and refresh it on every consented re-apply. The downgrade drops
  the column.
- **0079** — plan 168: `autopilot_runs.run_steps`, the durable per-node
  step trace (one append-return entry per executed node: step, kind,
  iteration, timing, whitelisted args/output summaries, abort marker). A
  ledger, not checkpoint history — checkpoints stay resume-only and
  TTL-pruned, the trace survives restarts and prunes and dies with the
  goal via the run cascade. JSONB with a dialect-safe `'[]'` server
  default (the NOT NULL add on SQLite); rebuildable forward only, so the
  downgrade drops it and pre-0079 runs read `trace_available=false`.
- **0073** — plan 148: `skill_changes`, the append-only skill lifecycle
  journal (`created | updated | promoted | auto_promoted | deprecated |
  restored | merged | deleted` — `event_allowed` CHECK mirrors
  `SkillEventKind`; actor `admin | system | sync | job | user` —
  `actor_kind_allowed` mirrors `SkillChangeActor`). `skill_id` is
  nullable with ON DELETE SET NULL and every row carries denormalized
  `skill_key`/`skill_label` snapshots, so deleting a skill keeps its
  audit trail (postings journal cascades because postings are the
  aggregate root; skill deletion is an admin decision worth keeping
  history for). `actor_ref`/`detail` are ids and capped diffs only.
  Composite indexes (skill_id, occurred_at) for the FK + newest-first
  read and (skill_key, occurred_at) for the after-deletion lookup.
  Written only through the `SkillChangeJournal.record` seam in the
  mutation's own transaction (admin taxonomy seams, the plan-147
  auto-promotion, proposal creation, tree-maintenance writes);
  downgrade drops the table (operational history).
- **0072** — plan 142: `posting_changes`, the append-only posting
  mutation journal (actor `sync_run | extract_llm | detail_fetch |
  company_match | retag | manual | expiry` — `actor_kind_allowed` CHECK
  mirrors the `PostingChangeKind` enum; `reextract` deliberately absent,
  a re-extract journals as `extract_llm` with `actor_ref.trigger`).
  `actor_ref`/`operation` are ids and knobs only (the params-not-content
  law — content lives in `ai_generations`/`job_postings.raw`); `diff`
  holds capped field→{from,to} pairs plus the skills set-diff; outcome
  `ok | partial | error`. One composite index (posting_id, occurred_at)
  serves the FK and the newest-first history read. Written only through
  the `PostingChangeJournal.record` seam in the mutation's own
  transaction; downgrade drops the table (operational history). Covered
  by `tests/test_migrations.py::test_0072_posting_changes_roundtrip` +
  the enum↔CHECK parity wall.
- **0071** — plan 135 slice C: `job_postings.org_match_state`, the indexed
  projection of the `org_match` JSONB's `state` (`linked | pending |
  rejected`; `org_match_state_allowed` CHECK mirrors the vocabulary) —
  JSONB is not filterable dialect-safely and the "no company" audit filter
  must split gate-rejects from pairs still pending triage on Postgres and
  SQLite alike. Backfill reads the JSONB per row; the matcher and the
  triage service keep the two columns in sync. Downgrade drops the CHECK
  before the column (SQLite batch) and keeps the state in the JSONB.
  Covered by `tests/test_migrations.py::test_0071_org_match_state_backfill`
  + the enum↔CHECK parity wall.
- **0070** — plan 135: company entity resolution. Four tables —
  `organization_aliases` (alias + `alias_key` + provenance source
  `manual|learned|llm|url|merge|legacy` + `active|excluded` state;
  UNIQUE(org_id, alias_key)), `organization_match_exclusions` (global
  not-a-company labels + per-pair never-link; partial UNIQUE(label_key)
  WHERE org_id IS NULL), `organization_match_pairs` (the gray-band queue +
  verdict audit) and `organization_merge_suggestions` (org_a/org_b +
  status `open|accepted|dismissed`), whose `evidence` JSONB columns both
  carry `keep-open` inventory rows; plus `organizations.name_key` /
  `initials_key` indexed exact-lookup keys (backfilled) and
  `job_postings.org_match` JSONB link provenance. Fold:
  `organizations.aliases` JSONB graduates to alias rows
  (`source='legacy'`), the column dies (no-BC; downgrade rebuilds the
  JSONB), and the quality denylist seeds as `source='seed'` exclusion
  rows so it is admin-editable from day one. Landed as the renumber of
  the plan-135 branch's `0065`/`0066_org` lane onto main's head
  (`0069` → `0070` → `0071`; main's `0066_filter_presets` had taken the
  original slot — see `dev/migration-notes.md`). Covered by
  `tests/test_migrations.py::test_0070_company_entity_resolution_fold` /
  `::test_0070_denylist_seeds_as_rows`, the enum↔CHECK wall and the
  conftest `TABLES` coverage gate.
- **0069** — plan 139: `skills.parent_source`, tree-placement provenance
  (`parent_source_allowed` CHECK: curated | learned, NULL allowed).
  `curated` — a human set or deliberately cleared the parent, stamped by
  `TaxonomyService.update_skill` (whose fill-only guard now REQUIRES the
  `learned` stamp, so a machine fill can never claim human provenance);
  `learned` — the tree catch-up's fill; NULL — untouched, the only slot
  the catch-up fills (the write-time guard re-checks BOTH `parent_id` and
  `parent_source` in the same transaction). The edge seam's `remove()` /
  `reject()` heal stranded `learned` placements through
  `TaxonomyService.heal_learned_placement` (clear when no approved `is_a`
  row supports the parent; `curated` and NULL never touched). No data
  migration — existing placements keep NULL (fills-only-empty makes NULL
  degrade gracefully; pre-139 placements keep the sticky mirror
  semantics); a pre-139 deliberate clear left both columns NULL —
  indistinguishable from an untouched slot — so the first post-upgrade
  catch-up pass re-fills it once (as `learned`); the remedy for any
  unwanted fill (and for a stuck pre-139 placement) is an explicit clear,
  which stamps `curated` and sticks. Covered by
  `tests/test_migrations.py::test_0069_skill_parent_source_roundtrip` /
  `::test_0069_parent_source_check_admits_the_vocabulary_and_null`, the
  enum↔CHECK parity wall, and the plan-139 provenance/heal tests.
- **0068** — plan 138 step 5: `schedules.task_allowed` widens with
  `skill_relation_learn` (mirrored CHECK — the `BackgroundJobType` member
  and the `Schedule.task` vocabulary grow together; `0067` reserved the
  kind slot but not the task vocabulary). The **mirrored-CHECK duality**:
  `schedules` carries TWO CHECKs with job-type vocabularies —
  `kind_allowed` (ScheduleKind) *and* `task_allowed`
  (BackgroundJobType) — and widening one but not the other 500s schedule
  inserts just the same; the `test_schema_contracts.py` `SCHEDULE_TASKS`
  parity tuples + the migration round-trip pin both. Downgrade deletes
  the schedule rows carrying the task first. Covered by
  `tests/test_migrations.py::test_0068_skill_relation_learn_task_roundtrip`
  + the enum↔CHECK parity wall (`test_schema_contracts.py`).
- **0067** — plan 138: `skill_relations`, the typed edge table over
  `skills` (is_a | synonym | part_of | related_to; `status` proposed →
  approved | rejected where rejected is the negative edge; `source`
  llm | manual | import | derived; nullable `confidence` CHECK 0–1;
  `evidence` JSONB — inventory row `skill_relations.evidence ::
  keep-open`; `decided_by`/`decided_at` for the review queue).
  Symmetric kinds are stored canonically ordered (from = lower UUID) and
  the `symmetric_pair_ordered` CHECK enforces it; `no_self_loop` and the
  `uq_skill_relation_edge` unique over (pair, relation) close the rest.
  The same revision widens `schedules.kind_allowed` with
  `system_skill_relation_learn` (the enum member ships with the widen to
  keep the enum↔CHECK parity wall green; the seeded schedule row and its
  job come with the learn job). Covered by
  `tests/test_migrations.py::test_0067_skill_relations_roundtrip` /
  `::test_0067_skill_relation_edge_guards`, the enum↔CHECK wall and the
  conftest `TABLES` coverage gate.
- **0062–0066** — notes pending (pre-existing gap from other plans;
  deliberately not backfilled here).
- **0061** — plan 134: `source_runs`, the ingestion run ledger (one row
  per `sync_source` attempt: trigger `manual|scheduled`, status
  `ok|degraded|failed|skipped`, started/finished, duration_ms,
  items_synced, bounded error + the `report` JSONB — inventory row
  `source_runs.report :: keep-open`; FK CASCADE to `job_sources`,
  index `ix_source_runs_source_started`). Covered by
  `tests/test_source_runs.py` + the conftest `TABLES` coverage gate.
- **0060** — plan 130b: `job_sources` gains `query_batch_size`
  (INTEGER NOT NULL DEFAULT 1, CHECK `query_batch_size_allowed`
  BETWEEN 1 AND 3) — how many rotating role groups one radar-mode sync
  searches; executed strictly sequentially. Covered by
  `tests/test_query_mode.py` and the head assertions.
- **0059** — plan 130: `job_sources` gains `query_mode`
  (`static` | `radar`, default `static` = today's behavior, CHECK
  `query_mode_allowed`) and the nullable `query_cache` JSONB (the merged
  radar query artifact: role groups + provenance + rotation cursor;
  inventory row `job_sources.query_cache :: keep-open`). Purely
  additive. Covered by `tests/test_query_mode.py` and the head
  assertions in `tests/test_migrations.py` / `tests/test_autopilot.py`.
- **0057** — plan 129 phase 4a: `job_radars`, the profile's saved
  job-search configuration (1:1 per profile, CASCADE; keywords/
  locations/seniority/source_keys as typed JSON lists, onsite
  preference, salary floor + currency on the normalized annual basis,
  cadence + enabled CHECK-mirrored). Purely additive.
  Covered by `tests/test_migrations.py::test_0057_job_radars_roundtrip`
  and `tests/test_job_radar.py`.
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
| `embedding_model_profiles` | `embedding_profile_model.py` | Admin tokenizer/limit override per provider-class + model (plan 52 T2a/T2b): tokenizer kind/identifier/revision/checksum/exact, max input tokens, per-request batch item/token limits and the default token `ChunkConfig` preview. Kinds are `tiktoken`, `hf_tokenizers` and `heuristic`; `sentencepiece` is reserved. Curated rows live in code (`app/ai/tokenizers/registry.py`) with HF provenance (repo/revision/SHA-256/license/source URL); the resolver order is admin → curated → conservative fallback, keyed on `(provider_class, model_name)` — never a model-name substring. A row is configuration, not a chunk/space rewrite. Fetched HF artifacts are cached at `<data_dir>/tokenizers/<sha256>/tokenizer.json`, not in the database |
| `ai_generations` | `ai_model.py` | The AI audit ledger (task, model, tokens, output, latency, run linkage) plus the caller-supplied retrieval tags (`metadata` + `metadata_schema_version` — space/kind/view/chunk index only, never text) |
| `ai_budgets` | `ai_model.py` | Budget tracking |
| `ai_skill_packs` | `skill_pack_model.py` | Versioned instruction data |
| `vector_spaces`, `vector_documents`, `vector_records` | `vector_model.py` | The family vector store (plan 50): versioned embedding spaces, polymorphic source documents (kind + `source_id` + scope), and one record per view/chunk with a content hash, a `text_ref` pointer and — only under the linear backend — the vector BLOB. The physical per-space index (`vec_*`, HNSW or `vec0`) is provisioned by a job/migration, never Alembic |
| `retrieval_query_rollups`, `retrieval_coverage_snapshots` | `vector_model.py` | Bounded operational telemetry (plan 51 Q0 schema, first written by the P1d reconcile pass): query-health buckets and per-kind coverage points (`total`/`missing`/`stale`/`failed`/`embedded` + the sampled ANN recall) |
| `ai_mcp_servers` | `mcp_bridge_model.py` | External MCP server registrations |
| `mcp_tokens` | `mcp_bridge_model.py` | Hashed MCP access tokens (personal or instance-wide), closed `scopes`, rotation + per-token revocation |

## Growth, engagement and notifications

| Table(s) | Model | Holds |
|---|---|---|
| `growth_plans`, `growth_plan_steps` | `growth_model.py` | Roadmaps |
| `learning_resources` | `growth_model.py` | Resources for skill gaps |
| `search_history` | `engagement_model.py` | Saved/recent searches |
| `smart_query_cache` | `smart_search_model.py` | Cross-user NL-search cache (plan 179): `query_hash` PK = sha256 of the normalized query, closed `SmartSearchSpec` JSONB, `created_at`. TTL-pruned (7 days) by the daily smart-digest job — cache data, never a record |
| `notifications`, `notification_recipients`, `notification_deliveries` | `engagement_model.py` | The notification funnel (dedup keys, delivery state); `channel` spans `in_app`/`desktop`/`browser`/`email`/`webhook`. A `pending` delivery with `error = deferred:<quiet_hours|digest_mode>` is email waiting for the next digest run; webhook rows stay `pending` until the queued delivery job reports |
| `user_channel_configs` | `engagement_model.py` | Per-user, per-channel config — email: `address` override, `digest_mode`, `pending_address`/`verification_hash`/`verification_expires_at` while double opt-in is open; webhook: `url` + `template` (`generic`/`slack`/`teams`/`telegram`/`ntfy`) — sealed `secrets` (webhook token only; URLs are not secrets) + `verified_at` |
| `notification_kinds`, `notification_kind_prefs`, `notification_rules`, `notification_preferences`, `notification_subscriptions` | `engagement_model.py` | Kind registry, per-rule caps/cooldowns, quiet hours |

## Scheduling and operations

| Table(s) | Model | Holds |
|---|---|---|
| `background_jobs` | `background_job_model.py` | The job queue (status, result, run linkage) plus the nullable `idempotency_key`/`lock_key` handles and their active-status partial unique indexes (plan 51 Q1a seam; the runtime lands in Q1b) and the bounded live `progress_detail` counters (plan 52 T4). `tokenizer_fetch` rows (plan 52 T2b) are plain jobs: they are not `VECTOR_*` runs and never take a space lock |
| `schedules` | `schedule_model.py` | Trigger definitions, misfire policy, claimed/queued state |
| `app_settings` | `settings_model.py` | Instance settings (AI config, web tools, notification config) |
| `interview_sessions` | `interview_model.py` | Interview plans, rubric aggregates, status |

## Related

- [Architecture](architecture.md) — how these fit together at runtime
- [Migrations](migrations.md) — changing the schema
- [AI layer](ai-layer.md) — the `ai_*` tables in context
