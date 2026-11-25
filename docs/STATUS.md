# Project status

Single source of truth for **what exists** and where the project is. Update
this page in the same commit as any behavior change; the per-release detail
lives in [CHANGELOG.md](https://github.com/neuronection/career-assistant/blob/main/CHANGELOG.md).

**Current phase: public beta — v0.17.0-rc.2 (release candidate).** Both product
modes are first-class and CI-covered: the self-hosted web platform (Postgres,
Docker) and the local desktop app (pywebview + SQLite). The schema is
dialect-aware (Postgres + SQLite verified against one Alembic chain). Pre-1.0
REST and schema surfaces may still change.

Six surfaces ship as **beta** (reachable, with a visible Beta chip and one
expectation line in the app): Career Autopilot, Contacts and outreach,
Interview prep, the Growth toolkit, Career paths and Market intelligence. The state of every surface
lives in `frontend/src/config/features.json`, which the sidebar, the tour and
the [README feature-status table](https://github.com/neuronection/career-assistant#feature-status)
all read.

## Module status

| Area | Status | Notes |
|---|---|---|
| Job catalog (family tree + typed relation graph, rich attributes, search) | done | Taxonomy referenced by stable `key` slugs; relations carry weight/rationale/source |
| Admin taxonomy & review queues | done | One batch-selection contract across interests, skills, relations, translations, enrichment, draft paths and job proposals: scoped select-all, hidden-by-filter reporting, per-item outcomes |
| Catalog mapping coverage & triage | done | Tools → Mappings: the funnel/accounted-for gate, typed outcomes, weak review + scoped stale/all re-decide, per-source/per-type breakdowns, detail-now/re-propose/bulk map, and the `title_key` duplicate-type guard |
| AI job generation + relation suggestion | done | Pydantic-validated into typed JSONB; audited |
| Student profile (onboarding wizard, start paths, typed sections) | done | Shared section cards; autosave; open-vocabulary skills |
| CV intake (PDF/text/photo → review-first draft) | done | Per-item review, confidence + evidence, field-level basics conflict handling |
| Matching (AI score + rationale, human score/status) | done | Positives, negatives, missing prerequisites |
| Deterministic fit engine + metric model | done | Per-dimension breakdown, re-weightable; RIASEC/work-values; no popularity term |
| Rankings, filters, compare tray (`/compare`) | done | Combines AI + human scores |
| Express start & target mode | done | Target dashboard, completeness ring |
| Universities (PDF intake → reviewable draft, job pathways) | done | Manual-review by design; never writes unreviewed |
| Career paths as data | done | Curated + AI-drafted routes over relation edges |
| Data providers & versioned seed packs | done | Tools → Sources → Data providers: bundled presets + the official pinned repository + public Git/index/uploaded packs; immutable content-addressed versions, plan preview, exact-digest approval, priority conflicts, provenance; retirement keeps created sources |
| Provider follow/hide & visibility | done | `/radar` follows providers and hides sources; hidden wins over selected-provider mode, the radar picker and Explore filters across Explore, live list, radar, digests, saved-search runs, RSS and chat |
| Posting connectors (ATS API, JSON-LD, RSS, CSV, paste-a-URL, MCP scripts, real job boards: Arbeitnow / Remotive / Jobicy) | done | Polite runtime live (SSRF guard, robots, rate caps); connector SDK + admin-opt-in T1 plugin registry; sealed secret slots; T3 script tier (mcp connector, external MCP servers, app-side row validation + audit — Phase 2); first real content — bundled T1 job-board connectors over live public feeds/APIs (watermark incremental, captured-truth fixtures, remotive repointed to the robots-allowed RSS feed, adoption manifests in the template repo). Manifests are FILES at the bundle root (`builtin/<key>/manifest.json`, the 2026-10-19 family unification — validated at registration incl. the docs-pointer binding; the four documented builtins ship `docs/` trees). The docs surface is live (2026-10-19): `GET /admin/postings/connectors/{key}/documentation` (tree + markdown, landing rule, traversal-safe, raw HTML neutralized) and a **Docs** action on the connector source rows (pointer present ⇒ affordance). Docs: the ten-chapter SDK doc set at `docs/dev/sdk/` (quickstart verified end-to-end, tree validated against the vendored docs-tree contract; superseded `docs/dev/extensions.md`) |
| Extension sources & the import layer (git import, consent, pins, GitOps) | done | https git sources + gated dev/test `local` variant; consent-gated digest-pinned installs (T3 managed spawn from the cloned content); no auto-apply path at all; GitOps desired-state reconcile (boot + hourly) moves pins only; private-repo credentials as sealed secret slots. The surfaces render through the family integrations kit (sources list, add-source dialog, consent dialog, config form) — local copies deleted same-commit |
| Declarative extension surfaces (mini-app pages/panels, SurfaceRenderer) | done | T0 mini-app imports (the `mini-app` kind — the reference CV-utility `cv-gallery/` in the template repo); `app/extensions/surfaces.py` registration-time node law + evidence rule; `/extensions/<id>` routed page + `/extensions/surfaces` API (label resolution, reject-unknown-id law, data-block caps, facet derivation from configSchema); `ui:window` degrades to page on the web host; `run` honored as the typed-action funnel (`run:export`); rendered through the family SurfaceRenderer (shared fixture wall, no extension markup) |
| T2 sandbox runner (imported code behind the capability RPC) | done | Python sandbox port: `extension.py` artifacts install as tier T2 and execute one-subprocess-per-extension speaking `capability-rpc/1` — polite net.fetch scoped to declared domains (all hops), extension-owned state (quota'd), schema-validated items, secrets as host-side HEADER substitution only (URL placeholders refused typed; values never cross the seam in either direction — envelopes and error details scrubbed); frozen module surface (audit-hook wall), per-call wall-clock watchdog + POSIX RLIMIT_AS + quotas + one audit row per call; sandbox death self-disables with a surfaced reason, boot reconciliation interrupts orphans; escape matrix + rpc fixture walls green (owner gate-override recorded 2026-10-16); Windows memory cap NOT enforced (disclosed residual) |
| Deep posting extraction (skills/salary/prerequisites/benefits with evidence) | done | Extraction v4; low-confidence fields suppressed, never guessed; prerequisites typed and fit-matched |
| Companies (reviewed profiles + derived hiring stats, all postings per company) | done | Facts are reviewed manual/derived — never guessed; financial claims carry source + as-of; merges re-point or refuse |
| Explore page (facet filters, saved searches, cursor pagination) | done | Live counts; per-posting match score; tri-state include/exclude on every axis — skills via the catalog picker, organization from the companies catalog, sources include/exclude; card entity menu: click/right-click a card's skill or company (right-click for spec values) to include/exclude it with undo, plus skill peek and skill/company page shortcuts |
| Job radar (saved search config + explore integration; digests through the notification funnel) | done | Per profile; salary floor on the normalized annual basis; nothing inferred |
| Market intelligence (stats page `/postings/stats` + pulse rails on /postings and /companies; **beta**) | beta | One filter vocabulary with Explore (`parse_explore_filters` + the conditions builder compiled once per request); Overview/Demand/Skills/Pay/Companies tabs over one composite request with one `as_of`, per-card errors and an 8s per-card timeout recovery; explicit status basis (`open` vs `all` = every status except hidden, matching the list); window+basis+segment-carrying drills into `/postings`; per-currency salary bands (no FX), career-family demand, source freshness; live bounded aggregation, no cache tables. Documented in `docs/user/market-stats.md`; registry key `/postings/stats` (beta) |
| Semantic search (embeddings + hybrid RRF retrieval) | done | pgvector optional; semantic is a ranking signal, never a filter gate |
| Retrieval operations (Tools → Retrieval + Audit → Retrieval) | done | Active space/backend/model, bounded reindex, token-aware v2 build beside the retained v1 space, coverage+quality cutover gate, maintenance, idempotent actions and alerts; the Audit tab is read-only. Operator runbook: `docs/dev/retrieval-ops.md` |
| Career Autopilot (goal agent, budgets, explainable shortlists) | done | Scheduler cadence or on demand; never auto-applies |
| Growth toolkit (roadmaps, near-miss radar, market snapshots, check-ins) | done | |
| Engagement loop (discovery feed, history, bookmarks, alerts) | done | Threshold alerts via the notification funnel |
| Assessment (JobTypeMatch 4-phase pipeline) | done | Resumable; evidence reconciliation flags conflicts |
| Career stages | done | Presets are suggestions, never hidden scoring branches |
| CV Studio — template bank + design-token editor | done | Versioned templates; printed-page visual review |
| CV Studio — on-demand AI generation + vision polish loop | done | LangGraph draft flow; bounded fix loop; restorable versions |
| CV Studio — item variant library (text + bullets) | done | Staleness/orphan detection; one-variant window per ref |
| CV Studio — exports (PDF/DOCX/Markdown/JSON/ATS text) | done | PDF is the page-count truth (real print engine) |
| Cover letters per posting | done | Brief + evidence-cited AI drafts (unbacked paragraphs flagged, never auto-applied); created from CV Studio or a posting; same templates, versions and exports as CVs |
| Application craft (gap report, CV parser view, application kit) | done | Evidence-first rows with verbatim quotes; the kit is review-first and writes nothing until applied; no headline percentage |
| Eligibility gates (visa, language, grade) | done | Unknown never excludes; `case_by_case` is a warning; a per-posting override removes the gate without invalidating the cached fit |
| Capture and people (bookmarklet, contacts, outreach log) | done | `?capture=` plus the `/postings` entry point; contacts are flat, exported with the account and deleted with it; drafts are copy-only and cite evidence |
| Posting trust and safety signals | done | Descriptive facts (reposts, first seen, cross-source duplicates, six deterministic risk flags), never a verdict; flags are computed on read |
| Salary benchmarks and offer comparison | beta | Posted-pay cells honour the sample floor (no number below it), per currency and never converted; offers annualize pay and net cost of living without negotiation advice |
| Interop (JSON Resume import/export, ICS interview import) | done | Review-first; collections and payloads are bounded; ICS goes through the family codec |
| Craft practice (STAR stories, screening answers, bullet coach) | done | Deterministic coaching and cited evidence; nothing is auto-written or auto-filled |
| Career orientation (degree roles, NACE competencies, market guide) | done | Deterministic mapping, sourced guide cards, no scores |
| Chat (tool-calling over your data, grounded digests) | done | Checkpointed LangGraph turn graph; the floating launcher is the default surface (the side panel is an explicit, remembered choice); dictation appears unless the effective `transcribe` assignment is explicitly unconfigured (then a full-width, dismissible settings notice above the input; unknown config keeps the mic) |
| Chat profile proposals (HITL cards, before/after preview, revert) | done | Read-before-edit gate; anchored granular edits; never auto-applied |
| Builder copilot (chat → builder operations, vision self-review) | done | Same audited op path as UI buttons |
| Interview prep (posting-grounded practice + rubric) | done | Weak-area retry; learning resources |
| Notifications (single funnel, channels, quiet hours, digests) | done | Desktop native toasts |
| Scheduler (one periodic engine) | done | Decides WHEN, only enqueues jobs; misfire policies + backoff |
| Desktop app (pywebview window + tray, background scheduler) | done | Single-instance lock; auto-start opt-in |
| Desktop packaging (deb / AppImage / Windows exe) | done | Tag-driven releases; `careerassistant enginecheck` probe |
| MCP server (`/mcp`, read-scope tools) + client bridge | done | Token rotation; per-host rate limiting; audited + budgeted |
| Identity & auth (family `auth-kit`) | done | Cookie sessions + double-submit CSRF, key-separated token contract, DB-authoritative init-only instance modes (fail-closed), desktop DIM + shell-secret gate; user management is the kit's §12 surface with the shared `AdminUserTable` (Settings → Users) and account self-service (Settings → Account: sessions, password change, deletion). The §4 init + boot guards + §16 knob routing are the shared kit glue (`app/auth/install.py`, `nx_auth.boot`); S14 §4.5 transition cases; prefixed-only `CAREER_*` config with the data/config dir split, `main.py` split (238 ln), one app construction per process |
| AI gateway (single structured-output path, DB-only config) | done | Audited in `ai_generations`; mock provider dev/test-only — a visible "Mock provider active — dev only" chip appears whenever it serves a call. The bootstrap reports the effective AI status, an unconfigured first run opens the setup step (`/onboarding/setup`), every provider-needing surface offers the same prompt, and chat failures render typed copy (unconfigured / budget / rate limit). AI settings are scope-separated: My AI Configuration (`/settings/ai`, user) and Instance AI Configuration (`/settings/ai-admin`, admin), with inherited instance assignments shown on the personal Tasks tab |
| Uniform AI settings (§15 BYOK setup + decision models) | done | Preset tiles → guided setup → defaults-first assignments on the assistant-ui kit; capability-slot defaults (`default` pseudo-task gone); decision funnel (`app/ai/decide/`) with the `systemone` transport, D2b routing + scope-chain fallback, audited in `ai_generations`; byok gate R1–R7 + alignment strict in CI |
| Skill packs (versioned instruction data) | done | Tone/structure only; validators untouched |
| Production self-host stack (prod + standalone nginx, TLS) | done | See [dev/deployment.md](dev/deployment.md) |
| Object storage (documents, CV pages, exports) | done | `DocumentStorage` over the family contract: local on desktop/self-host, `s3`/`azure_blob` under a cloud profile; server-generated keys with a `documents.object_key` backfill and legacy dual-read; CV page objects and streamed exports; desktop backups fail closed under an object backend. `/health` carries a cached storage row (degrade-open, 503 only when required/sustained) and boot logs one redacted storage line; AWS/Azure deployment profiles and a manual cloud smoke workflow are documented. Runbook: [dev/storage.md](dev/storage.md) |
| Backups (DB + uploads scripts) | done | Desktop/self-host only: SQLite snapshot + uploads + keys, refused under an object backend; the compose sidecar dumps PostgreSQL. Built-in backup/export UI planned |
| i18n coverage | in progress | Locale files under `frontend/src/locales/` |

## Known limitations

Honest boundaries, not necessarily bugs — the full list lives in the
[root README](https://github.com/neuronection/career-assistant/blob/main/README.md#scope--limitations):

- Pre-1.0 APIs and schemas; pin a tag if you depend on them.
- v0.17 is a fresh-baseline release: a pre-v0.17 database is not upgradeable.
  The desktop app moves the old datastore aside on first launch (nothing is
  deleted) and shows a one-time notice; PostgreSQL deployments are preflighted
  at boot with guidance — recreate the volume (`docker compose down -v`)
  instead of migrating.
- Single-container scale — one uvicorn process serves API + SPA; no
  horizontal scaling or worker split yet.
- Single-tenant — no multi-school/organization model on the v1 roadmap.
- AI features need a configured provider in production (503 until an admin
  configures one); the mock provider can never serve production.
- University intake is a reviewable draft, never an official data feed.

## Up next

- **Career OS depth close-out** — the Career OS depth surfaces are shipped; what
  remains is the docs/status close-out pass, the deferred 2FA slice (blocked
  on auth-kit MFA) and the deferred correctness items tracked in the
  2026-11-12 audits (AI-audit PII redaction on deletion, capture provenance,
  ICS-apply concurrency, price-override uniqueness).
- **Market intelligence successors**: currency normalization
  ahead of the analysis tabs (196), sources & data-quality operations
  with saved views (197) and the personal "My market" lens (198).
- **Uniform taxonomy maintenance agent**: one evaluated
  pipeline for job types, skills and relations.
