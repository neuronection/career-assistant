# Architecture

Career Assistant is a **dual-mode product**: a self-hosted web platform
(Postgres, Docker) and a local desktop app (pywebview + SQLite). Both modes
are first-class, CI-covered, and share one codebase — the schema is
dialect-aware (Postgres + SQLite verified) and neither mode may break the
other.

## Repo map

```
├── backend/
│   ├── app/            # FastAPI: api/, services/, models, ai/, connectors/
│   ├── alembic/        # migrations (dialect-aware)
│   ├── careerassistant/  # desktop entrypoint (python -m careerassistant)
│   ├── tests/          # pytest (async; career_test DB)
│   └── venv/           # dev virtualenv (PEP 668: never system Python)
├── frontend/           # React 18 + Vite + TS + Tailwind + Zustand SPA
├── docker/             # compose taxonomy + Dockerfile + nginx confs
├── packaging/          # PyInstaller spec, deb/AppImage/Windows build scripts
├── scripts/            # run-dev.sh, ops + test + seed scripts, dev lib
└── assets/             # canonical brand assets
```

## Runtime topology

```mermaid
flowchart LR
    subgraph Client["Browser or pywebview window"]
        FE[React SPA]
    end
    subgraph Server["One process: API + SPA (same origin)"]
        API[FastAPI REST · single-user mode by default<br/>(JWT validated when presented; family auth later)]
        BG[Background tasks<br/>PDF parsing · AI generation]
        REG[Registries<br/>connectors · scheduler triggers<br/>chat tools · skill packs]
        MCP[MCP server<br/>/mcp · read-scope tools]
        EMB[Embeddings<br/>ai_embeddings · hybrid retrieval]
    end
    subgraph Data
        DB[(Postgres web / SQLite desktop<br/>typed columns + JSONB)]
        RQ[(Redis · reserved)]
    end
    LLM[Your LLM<br/>OpenAI-compatible]

    FE --> API
    API <--> DB
    API --> BG
    BG <--> DB
    REG --> API
    AG[Structured-output AI] --> LLM
    AG --> API
    MCP --> API
    EMB <--> DB
    EMB --> AG
```

The frontend talks to **domain endpoints** optimized for the UI (catalog
tree + graph, profile, matching, universities, chat, AI settings). All AI
work runs through one structured-output pipeline (`ainvoke_structured` in
the gateway, `app/ai/gateway.py`): resolved provider → LangChain chat
model (`app/ai/chat_models.py` is the only module that touches provider
SDKs) → pydantic-validated response → audited row in `ai_generations`.
There is no side door around it.

## Extension points are registries

- **Posting sources** only via the connector SDK (`app/connectors/`,
  entry-point group `career_assistant.connectors`, admin allowlist).
- **Periodic work** only via the scheduler (`app/services/scheduler/`;
  triggers via `career_assistant.scheduler_triggers`). The scheduler decides
  WHEN and only enqueues jobs.
- **Notifications** always flow through `NotificationService.emit` (single
  funnel; alert rules and their triggers live on `EngagementService`).
- **CV context sources** register in
  `app/services/cv_context_service.py` (`register_context_source`): each
  source binds a profile entity to a typed resolver; selection resolves
  deterministically into the renderer snapshot with per-item traceability.
  Ineligible profile data is not registered — it cannot reach a CV.
  The experience table splits into three sources (plan 70): `experience`
  resolves paid work only (jobs, internships, freelance), `projects`
  kind=project, `volunteer` kind=volunteer — keeping the generate
  machinery's `section kind == source_key` invariant, so generated CVs
  emit separate Work Experience / Projects / Volunteering sections.
- **Synthesized CV variants** (plan 62) live in the user-level
  `cv_synth_items` library (`app/services/cv_synth_service.py`), not in
  the profile: each variant cites typed source refs + source content
  hashes (staleness/orphan detection) and applies through the per-CV
  `context.synth_mode` overlay BEFORE editor overrides — precedence is
  override > synth > source, every application traced via
  `synth_applied` in the version's `context_resolution`. AI variant
  drafts go through the `cv_synth` gateway task; the CV copilot tools
  (`cv_synth_*`) are registry tools whose read scope surfaces in /mcp.
  One-shot generation is synth-aware (plan 69): in `prefer` mode the
  draft graph's `collect` node applies the same overlay before drafting
  (matching via `match_for_user`, no `CvDocument` needed), and the plan
  node may propose ≤3 gap variants per run — grounded by the
  deterministic `synthesize` node as DRAFT rows whose text feeds the
  draft (never editor overrides); the run result records
  `synth_applied`/`synth_proposed` and `POST /cv/synth/preview` powers
  the modal's pre-run match hint.
- **Synth maturity in CV Studio** (plan 72): the builder context panel
  renders the variant library as a synth tree under its sources
  (cross-listed per touched source, stale/orphan badges, status toggles
  with the one-variant-window supersede hint of `_supersede_slot`);
  manual variants are first-class — `POST /cv/synth` writes live
  variants through the shared `VariantEditor` (library page + builder
  context entry; language and posting scope recorded at creation, not
  editable after). The `synth` snapshot key is computed per CV in
  `CvBuilderService.resolution` (language + posting match via
  `match_for_user`, winner per ref, deduped to one entry per variant,
  excluded when already overlay-applied in `prefer` mode — never
  double-rendered) and consumed by the `synth_items` block kind
  ("Custom highlights": `title`, `selected` variant ids — empty =
  all applicable, `show_source_chips` prints the referenced items,
  `max_items`); markdown/ATS/DOCX exports branch on the kind via
  `_visible_blocks`. Item ordering is a JSONB block prop
  (`ItemsBlockProps.order`: ordered ids first, remainder in resolved
  order) applied by the renderer after its filters and before
  `max_items` truncation — the editor persists the full id array from
  the SectionsPanel reorder disclosure; `snapshot` rows carry their
  context item id (stamped in `resolution`) to make `order` robust
  against removed items.
- **CV block kinds** register in `app/services/cv_blocks.py`
  (`register_block_kind`): a kind binds a props schema + renderer
  behavior; blocks carry an `area` mark (`main`/`sidebar`, legacy
  `column` accepted) that sidebar layouts honor when grouping columns;
  cover letters reuse the pipeline through the `letter` kind. Design
  tokens include per-area paddings (plan 70): `main_padding_mm` /
  `sidebar_padding_mm` (unset = legacy defaults); sidebar templates pair
  them with `margin_mm: 0` so each area owns its spacing instead of the
  page.
- **CV polish loop** (plan 64) rides the same `cv_generate` background
  job after the `cv_draft` assemble node: the `cv_build_review` vision
  task (`app/ai/agents/cv_build_reviewer.py`) critiques the rendered
  pages + lint + a deterministic coverage matrix
  (`cv_context_service.build_coverage_matrix`), and a bounded
  fix/applicant node applies its `BuilderOp` suggestions through
  `cv_builder_chat.apply_operation` (same audited path as the
  copilot; op validation failures are logged and dropped). Design
  edits materialize as new template versions
  (`_styled_template` → `new_version`); variants ground through the
  `cv_synth` task and are kept (DRAFT row in `cv_synth_items`) or
  reverted by the next review. The polish trace lives on the final
  `ai_apply` version payload (`content["polish"]`) and in the job
  result — never in `working_content` (the builder replaces that
  dict).
- **UI-driven builder ops** (plan 71): `POST /cv/{id}/ops` applies the
  same `BuilderOp` vocabulary through `cv_builder_chat.apply_operation`
  — buttons and the copilot converge on one audited code path (bank
  templates auto-customize to a private copy; every response carries
  the refreshed state incl. the effective `template_id`). The builder's
  Template tab (`GET /cv/{id}/design` for initial state) exposes the
  full `DesignTokens` editor plus printed-page visual review
  (`POST /cv/templates/{id}/visual-review`), and the copilot's
  structured critique renders in the AI tab with one-click
  `safe_token_fixes` apply.
- **Language-display registries** live in `app/services/cv_languages.py`:
  ISO code → human name (30 languages, on-demand values render via
  title-cased fallback when the extraction/combobox vocabulary grows),
  profile level → representative CEFR band, and
  the proficiency-exam vocabulary that lets the `languages` block claim
  the latest matching certification inline (with
  `exclude_proficiency` dedupe on the certifications `items` block,
  plus an explicit `language_code` on certifications outranking the
  derived matcher). Templates select presentation props only; the merge
  logic is shared.
- **Metric dimensions** are a curated registry
  (`metric_dimensions` table, code spec in `app/seeds/metrics.py`):
  `user_metric_profile` stores measured values with provenance; the fit
  engine, filters and weight sliders read the same dimension keys.
- **The extraction feature map** lives in
  `app/services/feature_map.py`: rows bind every `PostingExtract` field
  to its real consumers, and the AI extraction prompt is generated from
  those rows — schema and prompt cannot drift.
- **CV pagination is estimated, then measured**: `cv_renderer` computes
  `estimated_pages` from per-column wrap math (font size, page size,
  sidebar width all factor in) and honors them per column (two-column
  layouts fill max(main, sidebar) pages — the columns table-based so
  they fragment across print pages). PDF exports record the measured
  Chromium page count onto the compiled version
  (`content.render.pages_actual`) and lint surfaces it next to the
  estimate; break-quality is CSS-only (`break-inside: avoid` on
  semantic units, `break-after: avoid` on headings).
- **Chat tools** register in `app/ai/tools/` (`AITool` data,
  single `run_tool` executor, entry-point group `career_assistant.tools`
  gated by `TOOL_PLUGINS_ALLOWLIST`). The autopilot's `run_autopilot` /
  `my_autopilot` are registry members with the `chat` audience; the CV
  builder copilot's `cv_*` operations are members with the
  `cv_builder` audience — read-scope state/visual-review plus write-scope
  builder mutations, all executing the same `cv_builder_chat` agent
  functions the turn loop uses.
- **Skill packs** are versioned instruction data in
  `ai_skill_packs` (37-style immutable versions; bank seeds in
  `app/seeds/skill_packs.py`). `app/ai/packs.py` resolves the latest
  published bank pack per task; the gateway appends it to the system
  prompt and pins `pack_key`/`pack_version` on every `ai_generations`
  row. Packs steer tone/structure only — validators are untouched.
- **Run linkage**: multi-step flows (CV generation, the polish loop) opt
  each gateway call into the audit ledger with a `RunRef` (run id =
  background-job id, stage label) — `ai_generations.run_id`/`run_stage`
  are plain nullable indexed columns (no FK), so the ledger outlives the
  run and single-call/sync paths stay indistinguishable from before
  (NULL columns, byte-identical behavior). The mid-run job mirror
  (`job.result.polish.llm_calls`) and the finalized polish trace carry
  the run's compact call ledger; an opt-in `with_audit_ref` on the
  gateway returns the audit row just written without a second SELECT.
  `GET /cv/{id}/runs` assembles per-CV runs (generation + every polish
  re-run) from the job rows and their run-linked audit rows — the
  builder's "Runs & metrics" popup (65.5) reads this, not a new ledger.
  The presentation layer is the family library `flow-trace` module
  (`FlowTraceCard` + `FlowTelemetryStrip`, schema-owned, zero app data
  joins); mock-provider rows badge as simulated, never fake spend.
- **MCP surfaces** live in the AI layer:
  `app/ai/mcp_server.py` exposes the registry's **read-scope tools
  only** over Streamable HTTP at `/mcp` (FastMCP; token persisted in
  the data dir, live admin rotation `POST /ai/mcp/token`; per-host
  rate limiting via `MCP_RATE_LIMIT`). The client bridge
  (`app/services/mcp_bridge_service.py` + `ai_mcp_servers`) keeps
  registration/discovery/allowlist; protocol plumbing stays in
  `app/ai/mcp_client.py` (alignment R2). Bridge invocations are audited
  + budgeted as `mcp_tool_call`.
- **Embeddings** flow through the `embed` task
  (EMBEDDINGS capability) into `ai_embeddings` (`app/models/
  embedding_model.py`, `app/services/embedding_service.py`) — packed
  JSONB vectors are the single source of truth on every dialect;
  pgvector is provisioned best-effort, never required. Hybrid retrieval
  (`app/services/hybrid_search.py`) RRF-fuses lexical + cosine rankings
  over the hard-filtered candidate set in explore's relevance sort —
  semantic is a ranking signal, never a filter gate.
- **Follow-up automation** is a scheduler slot
  (`system_followups` → `followup_sweep` job,
  `app/services/followups_service.py`): a stateless sweep over applied
  `posting_interactions` (+7d/+14d nudges, interview/offer check-ins)
  emitting through the notification funnel; sent-state lives in
  notification dedup keys, prefs in `preferences["followups"]`
  (`GET/PATCH /me/followups`).

## AI flows are LangGraph graphs

Multi-step AI flows are checkpointed LangGraph
`StateGraph`s under `app/ai/graphs/`. Nodes make one gateway
call or do deterministic work; the checkpointer is app-lifespan-owned
(`app/ai/checkpointer.py`: AsyncPostgresSaver web / AsyncSqliteSaver
desktop) and `thread_id` is the run id, so an interrupted run resumes
from its last completed node via `ainvoke(None, config)`. Long runs
execute on the job queue (`autopilot_run` job type,
`user_autopilot` schedule slot); the scheduler only enqueues.

Chat-bound flows stay on bounded structured turns instead of graphs when
each turn is a single gateway call (rule: don't graph-ify single-call
tasks): the CV builder copilot and the interview practice loop
 ride the standard chat turn with a `context.surface` branch;
their durable state lives in app tables (`cv_documents` working content /
`interview_sessions` plan + rubric), and resumability comes from the chat
transcript itself.

Both paths surface a shared **turn trace** to the user: the stream emits
family `tool_call` events (snake_case `duration_ms` on the wire) while
the phase/node events run, and the same data persists into the assistant
message's `metadata_json` as `tools[]` (execution windows +
capped `args_summary`/`result_summary`) and `nodes[]` (per-phase
`start_ms`/`duration_ms`) — the schema is JSONB dialect-safe and needs
no migration. For the builder copilot the trace is honest-by-construction:
the one structured planning LLM call stays a node (no synthetic tools),
the real work (state read, operations, visual review) shows as tool
cards, and an error turn records the node windows it reached before
failing.

PDF parsing and AI generation run as FastAPI background tasks; Redis ships
in the compose file for a later worker split (no Celery in v1).

## AI configuration is data, not env

AI providers/models/task assignments live exclusively in the database
(Settings → AI Configuration). There are deliberately no `AI_*` env vars.
Production starts unconfigured (AI endpoints answer `503` until an admin
adds a provider); in `APP_ENV=development` a mock provider is auto-provisioned
so the app works without keys.

## Modes & data

| Mode | DB | Shell | Packaging |
|---|---|---|---|
| Web / self-host | Postgres 16 (JSONB) | Browser | `docker/` compose stacks (single image serving API + SPA) |
| Desktop | SQLite (aiosqlite) | pywebview window + tray | PyInstaller → deb / AppImage / Windows exe |

Desktop data lives under the OS data dir; first launch creates a strong
`secret.key`, migrates and (optionally) seeds. Closing the window keeps the
app in the tray — scheduled work continues in-process.

## Dev loop & deployment

- Dev: `docker compose -f docker/docker-compose.dev-db.yml up -d` then
  `./scripts/run-dev.sh` (honcho: backend :8100 + vite :3100).
- Deploy: `docker/docker-compose.standalone.yml` (app + Postgres + nginx,
  TLS-ready) or `prod.yml` behind your own LB — see [deploy.md](deploy.md).
- Verification gates: backend pytest + ruff; frontend build + vitest
  (`AGENTS.md` has the exact commands).
