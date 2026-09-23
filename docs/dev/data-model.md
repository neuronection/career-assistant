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
| `users` | `user_model.py` | Accounts (single-user mode creates one default admin) |
| `profiles` | `user_model.py` | The structured profile document |
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
| `career_paths`, `career_path_steps` | `career_path_model.py` | Curated and AI-drafted routes |

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
| `job_sources` | `posting_model.py` | Configured connector sources |
| `job_postings` | `posting_model.py` | Live postings + extraction payload |
| `posting_skills` | `posting_model.py` | Extracted skills with level/priority/evidence |
| `posting_interactions` | `posting_model.py` | Seen/saved/applied funnel |
| `posting_fits` | `posting_model.py` | Per-posting fit |
| `market_snapshots` | `market_model.py` | Aggregated market data |
| `autopilot_goals`, `autopilot_runs`, `autopilot_findings` | `autopilot_model.py` | Goals, runs and explainable findings |

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
| `profile_proposals` | `profile_proposal_model.py` | HITL proposal cards (diff, snapshots, status, lineage) |
| `ai_providers` | `ai_provider_model.py` | Providers with `api_key_encrypted` (Fernet) |
| `ai_models`, `ai_task_assignments` | `ai_provider_model.py` | Models + per-task model assignments |
| `ai_generations` | `ai_model.py` | The AI audit ledger (task, model, tokens, output, latency, run linkage) |
| `ai_budgets` | `ai_model.py` | Budget tracking |
| `ai_skill_packs` | `skill_pack_model.py` | Versioned instruction data |
| `ai_embeddings` | `embedding_model.py` | Packed JSONB vectors (single source of truth) |
| `ai_mcp_servers` | `mcp_bridge_model.py` | External MCP server registrations |

## Growth, engagement and notifications

| Table(s) | Model | Holds |
|---|---|---|
| `growth_plans`, `growth_plan_steps` | `growth_model.py` | Roadmaps |
| `learning_resources` | `growth_model.py` | Resources for skill gaps |
| `search_history` | `engagement_model.py` | Saved/recent searches |
| `notifications`, `notification_recipients`, `notification_deliveries` | `engagement_model.py` | The notification funnel (dedup keys, delivery state) |
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
