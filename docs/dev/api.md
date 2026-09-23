# REST API

The backend exposes a versioned domain REST API plus a few non-versioned
endpoints. The OpenAPI schema is committed as a contract and gated in CI.

- **Base path:** `/api/v1` (the `api_router` in `app/api/v1/__init__.py`).
- **Interactive docs:** `/docs` (Swagger) and `/redoc` on a running backend.
- **Committed contract:** [`contracts/openapi.json`](https://github.com/neuronection/career-assistant/blob/main/contracts/openapi.json).
- **Non-versioned:** `GET /health`, `POST /shell/rendered` (desktop render
  beacon), and the MCP server mounted at `/mcp`.

## Authentication

Bearer JWT (`Authorization: Bearer <token>`) validated when presented. In the
default **single-user mode** a default admin is used automatically, so a
fresh install needs no login; with `SINGLE_USER_MODE=false` the
`/auth` register/login flow applies. See [security.md](security.md).

## Routers by area

| Tag / prefix | Module | Area |
|---|---|---|
| `auth` | `auth.py` | Register, login, token |
| `me` | `me.py`, `me_cv_data.py`, `me_photo.py` | Current user, CV data, photo |
| `profile` | `profile.py` | Structured profile sections |
| `profile-proposals` | `profile_proposals.py` | HITL proposal cards (approve/reject/revert/preview) |
| `experience` | `experience.py` | Experience workspace |
| `onboarding` | `onboarding.py` | Wizard + start paths |
| `skills`, `taxonomy`, `metrics` | `skills.py`, `taxonomy.py`, `metrics.py` | Taxonomy, skills, metric profile |
| `assessments` | `assessments.py` | JobTypeMatch runs |
| `jobs`, `paths` | `jobs.py`, `paths.py` | Catalog jobs, relations, career paths |
| `universities` | `universities.py` | Universities, departments, admissions |
| `documents` | `documents.py` | Uploads + parsing |
| `cv` | `cvs.py`, `cv_intake.py`, `cv_synth.py` | CV documents, versions, context, intake, variants |
| `cv-templates` | `cv_templates.py` | Template bank + design |
| `matching` | `matching.py` | Match insights, fit |
| `postings` | `postings.py` | Sources, postings, Explore, extraction |
| `autopilot` | `autopilot.py` | Goals, runs, findings |
| `engagement` | `engagement.py` | Feed, history, bookmarks, alerts |
| `growth` | `growth.py` | Roadmaps, near-miss, resources |
| `notifications` | `notifications.py` | Notification funnel + stream |
| `scheduler` | `scheduler.py` | Schedule CRUD |
| `chat` | `chat.py` | Sessions, messages, SSE streaming |
| `interview` | `interview.py` | Interview sessions |
| `background-jobs` | `background_jobs.py` | Job queue status |
| `ai` | `ai.py` | Contextual "Ask AI" assists |
| `ai-settings` | `ai_admin.py` | Providers, models, task assignments (admin) |
| `admin` | `admin.py` | Admin operations |

The authoritative endpoint list is `contracts/openapi.json` (or `/docs`).

## Errors

Domain errors map to consistent JSON shapes (`{"detail": "…"}`) via
exception handlers in `app/main.py`:

| Exception | Status |
|---|---|
| `AINotConfiguredError` | `503` (no AI provider configured) |
| `PermissionDeniedError` | `403` |
| `NotFoundError` | `404` |
| `ConflictError` | `409` |
| `AccountLockedError` | `423` |
| other `DomainError` | `400` |

Validation failures use FastAPI's standard `422`.

## Streaming

- **Chat** streams over SSE (`app/api/v1/chat.py`, `frontend/src/api/chatStream.ts`).
  Events carry the family's `tool_call` vocabulary (snake_case `duration_ms`
  on the wire) plus phase/node events. Reverse proxies must not buffer.
- **Notifications** have their own stream (`notificationStream.ts`).

## Pagination and filtering

Posting/Explore endpoints paginate by **cursor** and support rich facet
filters. Other list endpoints use standard offset/limit or return full sets.

## Middleware

`app/main.py` adds CORS (from `CORS_ORIGINS`), rate limiting
(`RateLimitMiddleware`, buckets `auth`/`ai`/`mcp`/`default`) and security
headers (`SecurityHeadersMiddleware`).

## The contract gate

`scripts/check-openapi.py` dumps the live schema, normalizes it (sorted keys,
version stripped) and either:

- rewrites `contracts/openapi.json` (`--update` — run in the **same commit**
  as the endpoint change), or
- exits non-zero with a diff when the schema drifted (`--check`, the CI
  default).

Add or change an endpoint ⇒ update the contract in the same commit.

## MCP

The read-scope tool registry is exposed over Streamable HTTP at `/mcp`
(FastMCP). It is token-authenticated, rate-limited and **read-only by
default** — see [ai-layer.md](ai-layer.md#mcp).

## Related

- [Data model](data-model.md)
- [AI layer](ai-layer.md)
- [Frontend](frontend.md) — the API client
