# Project status

Single source of truth for **what exists** and where the project is. Update
this page in the same commit as any behavior change; the per-release detail
lives in [CHANGELOG.md](https://github.com/neuronection/career-assistant/blob/main/CHANGELOG.md).

**Current phase: public beta — v0.14.0.** Both product modes are
first-class and CI-covered: the self-hosted web platform (Postgres, Docker)
and the local desktop app (pywebview + SQLite). The schema is dialect-aware
(Postgres + SQLite verified against one Alembic chain). Pre-1.0 REST and
schema surfaces may still change.

## Module status

| Area | Status | Notes |
|---|---|---|
| Job catalog (family tree + typed relation graph, rich attributes, search) | done | Taxonomy referenced by stable `key` slugs; relations carry weight/rationale/source |
| AI job generation + relation suggestion | done | Pydantic-validated into typed JSONB; audited |
| Student profile (onboarding wizard, start paths, typed sections) | done | Shared section cards; autosave; open-vocabulary skills |
| CV intake (PDF/text/photo → review-first draft) | done | Per-item review, confidence + evidence, field-level basics conflict handling |
| Matching (AI score + rationale, human score/status) | done | Positives, negatives, missing prerequisites |
| Deterministic fit engine + metric model | done | Per-dimension breakdown, re-weightable; RIASEC/work-values; no popularity term |
| Rankings, filters, compare tray (`/compare`) | done | Combines AI + human scores |
| Express start & target mode | done | Target dashboard, completeness ring |
| Universities (PDF intake → reviewable draft, job pathways) | done | Manual-review by design; never writes unreviewed |
| Career paths as data | done | Curated + AI-drafted routes over relation edges |
| Posting connectors (ATS API, JSON-LD, RSS, CSV, paste-a-URL) | done | Connector SDK + admin-opt-in plugin registry |
| Deep posting extraction (skills/salary/benefits with evidence) | done | Extraction v2; low-confidence fields suppressed, never guessed |
| Explore page (facet filters, saved searches, cursor pagination) | done | Live counts; per-posting match score |
| Semantic search (embeddings + hybrid RRF retrieval) | done | pgvector optional; semantic is a ranking signal, never a filter gate |
| Career Autopilot (goal agent, budgets, explainable shortlists) | done | Scheduler cadence or on demand; never auto-applies |
| Growth toolkit (roadmaps, near-miss radar, market snapshots, check-ins) | done | |
| Engagement loop (discovery feed, history, bookmarks, alerts) | done | Threshold alerts via the notification funnel |
| Assessment (JobTypeMatch 4-phase pipeline) | done | Resumable; evidence reconciliation flags conflicts |
| Career stages | done | Presets are suggestions, never hidden scoring branches |
| CV Studio — template bank + design-token editor | done | Versioned templates; printed-page visual review |
| CV Studio — on-demand AI generation + vision polish loop | done | LangGraph draft flow; bounded fix loop; restorable versions |
| CV Studio — item variant library (text + bullets) | done | Staleness/orphan detection; one-variant window per ref |
| CV Studio — exports (PDF/DOCX/Markdown/JSON/ATS text) | done | PDF is the page-count truth (real print engine) |
| Cover letters per posting | in progress | Entry points gated in the UI until the feature ships |
| Chat (tool-calling over your data, grounded digests) | done | Checkpointed LangGraph turn graph |
| Chat profile proposals (HITL cards, before/after preview, revert) | done | Read-before-edit gate; anchored granular edits; never auto-applied |
| Builder copilot (chat → builder operations, vision self-review) | done | Same audited op path as UI buttons |
| Interview prep (posting-grounded practice + rubric) | done | Weak-area retry; learning resources |
| Notifications (single funnel, channels, quiet hours, digests) | done | Desktop native toasts |
| Scheduler (one periodic engine) | done | Decides WHEN, only enqueues jobs; misfire policies + backoff |
| Desktop app (pywebview window + tray, background scheduler) | done | Single-instance lock; auto-start opt-in |
| Desktop packaging (deb / AppImage / Windows exe) | done | Tag-driven releases; `careerassistant enginecheck` probe |
| MCP server (`/mcp`, read-scope tools) + client bridge | done | Token rotation; per-host rate limiting; audited + budgeted |
| AI gateway (single structured-output path, DB-only config) | done | Audited in `ai_generations`; mock provider dev/test-only |
| Skill packs (versioned instruction data) | done | Tone/structure only; validators untouched |
| Production self-host stack (prod + standalone nginx, TLS) | done | See [dev/deployment.md](dev/deployment.md) |
| Backups (DB + uploads scripts) | done | Built-in backup/export UI planned |
| i18n coverage | in progress | Locale files under `frontend/src/locales/` |

## Known limitations

Honest boundaries, not necessarily bugs — the full list lives in the
[root README](https://github.com/neuronection/career-assistant/blob/main/README.md#scope--limitations):

- Pre-1.0 APIs and schemas; pin a tag if you depend on them.
- Single-container scale — one uvicorn process serves API + SPA; no
  horizontal scaling or worker split yet.
- Single-tenant — no multi-school/organization model on the v1 roadmap.
- AI features need a configured provider in production (503 until an admin
  configures one); the mock provider can never serve production.
- University intake is a reviewable draft, never an official data feed.

## Up next

- Notification-center library unification and health-assistant adoption.
- Pending rescope: match staleness/bulk re-score, E2E + typing gates,
  broader i18n coverage, demand-history trends.
- Cover letters: finish the per-posting flow and ungate its UI entries.
