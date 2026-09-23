# Adding features

End-to-end recipes for the common change types. Each recipe lists the files
you touch and the gates you must satisfy. Read
[development.md](development.md) for the conventions that apply to all of
them.

## Add a REST endpoint

1. **Schema** — add request/response models under `app/schemas/`.
2. **Service** — put the logic in the matching `app/services/*_service.py`;
   routers stay thin.
3. **Router** — add the route in the matching `app/api/v1/*.py` (or a new
   router, included in `app/api/v1/__init__.py`).
4. **Errors** — raise a `DomainError` subclass; the handlers in
   `app/main.py` map it to the right status.
5. **Contract** — run `python scripts/check-openapi.py --update` **in the same
   commit**.
6. **Tests** — a service- or API-level test in the matching `tests/test_*.py`.
7. **Docs** — update [api.md](api.md) (and the user page if behavior changed),
   plus `CHANGELOG.md` if user-visible.

## Add an AI task

1. **Enum** — add the task to `AITaskType` in `app/models/enums.py`.
2. **Registry** — add a `TaskDef` in `app/ai/tasks.py` declaring capabilities
   and tier.
3. **Agent** — add a module under `app/ai/agents/` with the prompt and the
   validated response schema (`app/ai/schemas.py`).
4. **Invoke** — call it through `app.ai.gateway.ainvoke_structured`; never
   touch a provider SDK outside `app/ai/chat_models.py`.
5. **Assignment UI** — the task appears in Settings → AI Configuration; make
   sure the model capabilities line up.
6. **Tests** — use the mock provider (`MOCK_AI=1`); assert the validated shape
   and the audit row.
7. **Gates** — `scripts/check-ai-alignment.sh`; docs in
   [ai-layer.md](ai-layer.md).

## Add a connector

1. Subclass `PostingConnector` in `app/connectors/builtin/` (or a plugin
   package) with a unique `key` and a `config_model()`.
2. Implement `fetch(config, state, *, transport)` emitting `RawPosting`s;
   never open sockets yourself.
3. Provide a `fixture_payload` and pass `ConnectorContractTests`.
4. For a plugin, ship the `career_assistant.connectors` entry point; it is
   admin-opt-in via `CONNECTOR_PLUGINS_ALLOWLIST`.
5. Docs in [connectors.md](connectors.md).

## Add a scheduler trigger or job type

1. **Trigger** — add a class in `app/services/scheduler/triggers.py`
   (validate + `next_after`), or ship it via the
   `career_assistant.scheduler_triggers` entry point.
2. **Job type** — add the `BackgroundJobType` member, a handler in
   `job_worker.py`'s `HANDLERS`, and a `ScheduleKind` mapping in
   `runner.py`.
3. **Migration** — if the enum is mirrored in a DB CHECK, widen the CHECK in
   the same commit (see [migrations.md](migrations.md)).
4. **Tests** — drive `SchedulerService(db).tick()` directly; the live loop
   never runs in tests.
5. Docs in [scheduler-and-jobs.md](scheduler-and-jobs.md).

## Add a CV block kind

1. Register the kind in `app/services/cv_blocks.py`
   (`register_block_kind`): a props schema + renderer behavior + `area` mark.
2. Handle it in `cv_renderer.py` and in the exports
   (`cv_export_service.py` `_visible_blocks`) so every format matches.
3. Add any icons to `cv_icons.py`; any tokens to the `DesignTokens` schema and
   the builder's Design tab.
4. Seed a template that uses it in `app/seeds/cv_templates.py` if relevant.
5. Tests + docs ([cv-engine.md](cv-engine.md), [ui-conventions.md](ui-conventions.md)).

## Add a registry tool (chat / MCP)

1. Add an `AITool` in `app/ai/tools/` with an audience (`chat`, `cv_builder`,
   `mcp`) and a scope (`read` / `write`).
2. Implement the single `run_tool` executor path — read-scope tools surface
   over MCP automatically; write-scope tools must go through the same audited
   service functions the REST forms use.
3. For a plugin, ship the `career_assistant.tools` entry point (gated by
   `TOOL_PLUGINS_ALLOWLIST`).
4. Tests + docs ([ai-layer.md](ai-layer.md)).

## Add a frontend page

1. **Route** — add it to `App.tsx` (and `config/nav.ts` /
   `config/settingsNav.ts` if it appears in navigation).
2. **Page** — a component under `pages/`; read
   [ui-conventions.md](ui-conventions.md) first.
3. **API** — add a module or function under `api/` using the axios client.
4. **State** — add a Zustand store only if the state is shared.
5. **Strings** — route user-facing text through i18n (`lib/i18n.ts`,
   `locales/`).
6. **Tests** — a vitest test in `frontend/src/tests/`; make API mocks honor
   the last write.

## Add a setting

1. **Backend** — store it in `app_settings` (or the relevant config JSONB);
   validate on write; expose via the settings API.
2. **Frontend** — surface it on the matching Settings page; use the shared
   primitives, never a bespoke control.
3. **Docs** — add it to the settings reference and, if user-visible,
   `CHANGELOG.md`.

## Before you commit

```bash
cd backend && ./venv/bin/pytest tests -q -n auto
cd backend && ./venv/bin/ruff check app tests && ./venv/bin/ruff format --check app tests
cd frontend && npm run build && npm run test -- --run && npm run lint
./scripts/check-changelog.sh
./scripts/check-ai-alignment.sh    # if you touched app/ai/
python scripts/check-openapi.py --check   # if you touched endpoints
```

## Related

- [Development workflow](development.md)
- [Testing](testing.md)
- [Architecture](architecture.md)
