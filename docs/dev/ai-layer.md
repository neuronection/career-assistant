# AI layer

Everything AI in Career Assistant lives under `backend/app/ai/` and flows
through **one gateway**. There is no side door. The family-wide rules are in
the `family-ai` skill; this page is the app-specific map.

## The gateway is the only invocation path

- `app.ai.gateway.ainvoke_structured` — the single structured-output call.
  Resolves provider → model, calls the LangChain chat model, pydantic-validates
  the response, and writes an audit row to `ai_generations`.
- `gateway.ainvoke_agent` — the tool-calling path (used by the chat turn and
  the CV enrich step).
- `with_audit_ref` — an opt-in that returns the audit row just written without
  a second SELECT (used by run-linked flows).

**`app/ai/chat_models.py` is the only module that touches provider SDKs.**
`scripts/check-ai-alignment.sh` enforces this (ADR-0008/0018).

## Configuration is data, not env

Providers, models and per-task assignments live exclusively in the database
(`ai_providers`, `ai_models`, `ai_task_assignments`) and are managed in
**Settings → AI Configuration**. There are deliberately **no `AI_*`
environment variables**. Production starts unconfigured — AI endpoints answer
`503` until an admin adds a provider.

The built-in **mock provider** is opt-in via the `MOCK_AI=1` infra knob
(dev/test only). When it resolves, the gateway self-registers deterministic
fixtures (`ensure_mock_registry` in `gateway.py`; builders in
`mock_chat.py`). With the knob off, mock rows are invisible to task
resolution; production refuses mock results regardless.

## Tasks and capabilities

`app/ai/tasks.py` holds the task registry (`TaskDef`); the task vocabulary is
`AITaskType` in `app/models/enums.py`. A task declares the **capabilities** it
needs (`AICapability`: `text`, `vision`, `tools`, `embeddings`, `audio`) and a
tier (`AITaskTier`), and a model is only assigned to tasks it can serve.

Representative tasks: `job_generate`, `relation_suggest`, `match_score`,
`university_parse`, `path_suggest`, `profile_analyze`, `posting_map`,
`posting_extract`, `target_resolve`, `chat`, `chat_ops`, `assist`,
`cv_draft`, `cv_synth`, `cv_parse`, `cv_build_review`, `cv_builder_chat`,
`cv_cover_letter`, `cv_template_design`, `interview_plan`/`interview_turn`/
`interview_debrief`, `assessment_generate`, `catalog_enrich`, `chat_title`,
`autopilot_run`, `embed`, `mcp_tool_call`, `transcribe`.

## Agents

One module per AI task under `app/ai/agents/` (for example `job_generator.py`,
`match_scorer.py`, `university_parser.py`, `posting_extractor.py`,
`cv_drafter.py`, `cv_build_reviewer.py`, `chatbot.py`, `interview_coach.py`).
An agent builds the prompt, calls the gateway and returns a validated shape.
Prompts are versioned (`app/ai/prompt_versions.py`).

## Flows are LangGraph graphs

Multi-step flows are checkpointed `StateGraph`s under `app/ai/graphs/`:

- `cv_draft.py` — the one-shot CV generation flow (plan → enrich → synthesize
  → assemble → review/fix).
- `autopilot.py` — the Autopilot run.
- `chat_turn.py` — the main chat turn: `retrieve` → `agent_round ⇄
  execute_tools` → `synth` → `hitl` → `finalize`.

The checkpointer is app-lifespan-owned (`app/ai/checkpointer.py`:
`AsyncPostgresSaver` web / `AsyncSqliteSaver` desktop) and `thread_id` is the
run id, so an interrupted run resumes from its last completed node via
`ainvoke(None, config)`. Retention: desktop prunes SQLite at boot
(`CHECKPOINT_TTL_DAYS`); the server prunes Postgres on the daily
`system_checkpoint_prune` schedule.

**Rule: don't graph-ify single-call tasks.** Flows whose every turn is one
gateway call stay as bounded structured turns (the CV builder copilot and the
interview practice loop ride the standard chat turn with a
`context.surface` branch).

## Tools

`app/ai/tools/` is a registry of `AITool` data with a single `run_tool`
executor. Tools declare an **audience** (`chat`, `cv_builder`, `mcp`) and a
**scope** (`read` / `write`). Plugins arrive via the entry-point group
`career_assistant.tools`, gated by `TOOL_PLUGINS_ALLOWLIST`.

- Read-scope tools surface over MCP.
- Write-scope tools (CV builder ops, profile proposals) execute through the
  same audited service functions the REST forms use.

## Skill packs

Versioned instruction data in `ai_skill_packs` (immutable versions; bank seeds
in `app/seeds/skill_packs.py`). `app/ai/packs.py` resolves the latest
published bank pack per task; the gateway appends it to the system prompt and
pins `pack_key`/`pack_version` on every `ai_generations` row. Packs steer
**tone and structure only** — validators are untouched.

## Embeddings

Embeddings flow through the `embed` task (EMBEDDINGS capability) into
`ai_embeddings` — **packed JSONB vectors are the single source of truth on
every dialect**; pgvector is provisioned best-effort, never required. Hybrid
retrieval (`app/services/hybrid_search.py`) RRF-fuses lexical + cosine
rankings over the hard-filtered candidate set in Explore's relevance sort —
**semantic is a ranking signal, never a filter gate**.

## Run linkage and budgets

Multi-step flows opt each gateway call into the audit ledger with a `RunRef`
(run id = background-job id, stage label) via `ai_generations.run_id` /
`run_stage` (plain nullable indexed columns, no FK — the ledger outlives the
run). `GET /cv/{id}/runs` assembles per-CV runs from job rows and their
run-linked audit rows. Budgets live in `app/ai/budgets.py` / `ai_budgets`.

## MCP

- **Server:** `app/ai/mcp_server.py` exposes the registry's **read-scope tools
  only** over Streamable HTTP at `/mcp` (FastMCP). The token is persisted in
  the data dir, with live admin rotation (`POST /ai/mcp/token`) and per-host
  rate limiting (`MCP_RATE_LIMIT`).
- **Client bridge:** `app/services/mcp_bridge_service.py` + `ai_mcp_servers`
  handle registration/discovery/allowlist; protocol plumbing stays in
  `app/ai/mcp_client.py`. Bridge invocations are audited and budgeted as
  `mcp_tool_call`.

## HITL

Chat-proposed profile mutations are **proposals, never auto-applied**:
detached `profile_proposals` cards resolved via idempotent approve/reject
endpoints (deliberately not LangGraph `interrupt()`, which pauses a whole graph
and cannot serve multi-card turns). See [architecture.md](architecture.md) and
[user/assistant-chat.md](../user/assistant-chat.md).

## Alignment gate

`scripts/check-ai-alignment.sh` enforces the architectural rules (gateway-only
invocation, no provider SDKs outside `chat_models.py`, DB-only config). Run it
before committing changes under `app/ai/`.

## Related

- [Architecture](architecture.md)
- [API](api.md) — the `ai` and `ai-settings` routers
- [CV engine](cv-engine.md) — the CV flows in detail
- [Data model](data-model.md) — the `ai_*` tables
