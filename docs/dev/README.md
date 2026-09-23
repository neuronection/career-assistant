# Career Assistant — developer guide

Career Assistant is a FastAPI (async SQLAlchemy) backend plus a React 18 +
Vite SPA, with a pywebview desktop shell around the same code. Two modes,
one codebase: a **dialect-aware schema** runs on PostgreSQL (web/self-host)
and SQLite (desktop), verified against one Alembic chain. Neither mode may
break the other.

Read this page for the map, then jump into the page you need. The
[architecture overview](architecture.md) is the canonical deep dive.

## Where to start

| If you are… | Read |
|---|---|
| New to the codebase | [architecture.md](architecture.md), then [development.md](development.md) |
| Setting up and running it locally | [development.md](development.md) |
| Changing the database schema | [data-model.md](data-model.md) and [migrations.md](migrations.md) |
| Adding or changing an endpoint | [api.md](api.md) |
| Touching anything under `app/ai/` | [ai-layer.md](ai-layer.md) |
| Writing a posting source | [connectors.md](connectors.md) |
| Working on periodic work or notifications | [scheduler-and-jobs.md](scheduler-and-jobs.md) |
| Working on CV generation, rendering or templates | [cv-engine.md](cv-engine.md) |
| Building UI | [frontend.md](frontend.md) and [ui-conventions.md](ui-conventions.md) |
| Writing or fixing tests | [testing.md](testing.md) |
| Thinking about secrets or the trust boundary | [security.md](security.md) |
| Deploying or packaging | [deployment.md](deployment.md), [desktop-packaging.md](desktop-packaging.md) |
| Adding a feature end-to-end | [adding-features.md](adding-features.md) |

## The pages

| Page | Covers |
|---|---|
| [architecture.md](architecture.md) | Modes, runtime topology, registries, AI flows, the structured pipeline |
| [development.md](development.md) | Bootstrap, commands, conventions, git worktrees, verification gates |
| [testing.md](testing.md) | pytest + vitest, parallel xdist databases, fixtures, what to mock |
| [data-model.md](data-model.md) | Tables by area, taxonomy joins, typed JSONB, dialect rules |
| [api.md](api.md) | The versioned REST surface, auth, errors, pagination, streaming, OpenAPI |
| [ai-layer.md](ai-layer.md) | Gateway-only invocation, tasks, agents, graphs, tools, packs, embeddings, MCP |
| [connectors.md](connectors.md) | The posting-connector contract, built-ins, plugin registry, contract tests |
| [scheduler-and-jobs.md](scheduler-and-jobs.md) | Job queue, job types, triggers, misfire policies, the notification funnel |
| [cv-engine.md](cv-engine.md) | Block kinds, renderer, context/variants, PDF measurement, the polish loop |
| [frontend.md](frontend.md) | Routing, stores, API client, assistant-ui, theming, i18n |
| [ui-conventions.md](ui-conventions.md) | Workspace pattern, primitives, tokens, motion, drag, previews, testids |
| [security.md](security.md) | Secrets, auth, the AI trust boundary, SSRF/uploads, rate limiting |
| [migrations.md](migrations.md) | Alembic discipline, sequential ids, dialect-aware and data migrations |
| [deployment.md](deployment.md) | Compose stacks, TLS, upgrades, backups, bare metal |
| [desktop-packaging.md](desktop-packaging.md) | PyInstaller, deb/AppImage/Windows, the PDF engine, enginecheck |
| [adding-features.md](adding-features.md) | End-to-end recipes for the common change types |

## Ground rules (short version)

1. **Structured over plain text.** AI outputs are pydantic-validated into
   typed JSONB shapes; reference the taxonomy by stable `key` slugs, never
   labels.
2. **AI only through the gateway.** Every AI call goes through
   `app.ai.gateway.ainvoke_structured` (audited in `ai_generations`). AI
   config is DB-only — never add `AI_*` env vars.
3. **Extension points are registries.** Posting sources via the connector SDK;
   periodic work only via the scheduler; notifications only through
   `NotificationService.emit`; CV blocks and chat tools via their registries.
4. **Keep both modes working.** The schema must stay dialect-aware (Postgres +
   SQLite verified). Run the backend suite and the frontend build before
   committing.
5. **Docs and code ship together.** Update the matching page under `docs/`
   (and `CHANGELOG.md` under `## [Unreleased]` for user-visible changes) in the
   same commit.
6. **No code comments** unless they explain a non-obvious decision; public
   APIs get Google-style docstrings.

The tracked [`AGENTS.md`](https://github.com/neuronection/career-assistant/blob/main/AGENTS.md) is the authoritative rule list; the
repo-local `dev/` directory holds only local scratch notes (gitignored).
