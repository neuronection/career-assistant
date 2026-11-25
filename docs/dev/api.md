# REST API

The backend exposes a versioned domain REST API plus a few non-versioned
endpoints. The OpenAPI schema is committed as a contract and gated in CI.

- **Base path:** `/api/v1` (the `api_router` in `app/api/v1/__init__.py`).
- **Interactive docs:** `/docs` (Swagger) and `/redoc` on a running backend.
- **Committed contract:** [`contracts/openapi.json`](https://github.com/neuronection/career-assistant/blob/main/contracts/openapi.json).
- **Non-versioned:** `GET /health`, `POST /shell/rendered` (desktop render
  beacon), and the MCP server mounted at `/mcp`.

## Authentication

Family auth-kit sessions (identity-auth §12): cookie + CSRF for the SPA,
`Authorization: Bearer <session token>` for CLI/MCP-style user clients.
Server deployments run `authenticated` (login/register; the first
registered user is the admin); desktop entrypoints run `open` (DIM — the
shell exchanges a session at boot). Every unauthenticated API request
answers `401`. See [security.md](security.md).

## Routers by area

| Tag / prefix | Module | Area |
|---|---|---|
| `auth` / `me` / `admin` (users, instance) | `nx_auth` (auth-kit) | Register, login, refresh, sessions, user management |
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
| `providers` | `providers.py` | Signed-in read view of published seed providers + endpoints |
| `admin/providers` | `providers_admin.py` | Provider CRUD, sync/upload, versions, plan/apply, items, sync runs, probe |

The authoritative endpoint list is `contracts/openapi.json` (or `/docs`).

## Provider API (seed packs)

The product vocabulary is **provider** (a seed-data publisher); the storage
tables stay `seed_*`. AI providers keep `/api/v1/ai/providers`.

Admin (`require_admin`, `/api/v1/admin/providers`):

- CRUD: `GET/POST /`, `PATCH/DELETE /{id}` (delete retires: disabled, pointer
  cleared, catalog replanned), `POST /discover` (read a `seed-repo.json` over
  a public git ref or the guarded registry transport; no writes) and
  `POST /import` (the same read, then one provider per pack — idempotent by
  kind/URI/subpath; nothing is fetched or applied afterwards).
- Content: `POST /{id}/sync`, `POST /{id}/upload` (file providers, pack-only
  zip), `GET /{id}/sync-runs`.
- Versions: `GET /{id}/versions`, `GET /{id}/versions/{vid}/plan`, and
  `POST …/approve|reject|revoke|apply`; `POST /{id}/adopt` takes
  `{version_id, seed_keys?}`.
- Items: `POST /{id}/items/{seed_key}/enable|disable|retire` (preset overlay,
  content stays pack-owned) and `POST /{id}/endpoints/{seed_key}/probe`
  (guarded fetch, status/elapsed/content-type only).

User (`/api/v1/providers`, signed in): `GET /`, `GET /{id}`,
`GET /{id}/endpoints` — enabled providers with a current approved version
only; messages exclude the URI, sync error, policy and version ledger, and
presets are filtered to `state=active AND enabled`. Follow/hide overlays are
a later increment; nothing here creates a `job_sources` row.

User preferences (`/api/v1/me`): `GET/PUT/DELETE
/provider-subscriptions/{provider_id}` (enabled, mode all/selected,
collections, filters) and `GET/PUT/DELETE /source-prefs/{source_id}` (hidden,
priority, filters). `hidden` is a hard deny applied before every other
filter; a selected-provider set narrows the visible sources (manual sources
stay visible). A missing user is the instance default. The predicate runs on
Explore, the live list, radar, digests, saved-search runs, RSS and the chat
search tool.

Sync never approves or applies; apply requires an approved version and holds
the global `provider_apply` lock. The old `/admin/postings/sources/catalogs` CRUD is removed; legacy catalog imports
fold into approved providers at priority 90 (`0019`).

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
filters. Filters and the `total` count run in SQL; `fresh`/`salary` sorts
are pure keyset pages, while `fit`/`relevance` rank the newest
`limit × 5` matching postings (floor 100, cap 500) against the
`posting_fits` cache — `total` remains the exact filtered count. Other
list endpoints use standard offset/limit or return full sets.

## Middleware

`app/main.py` adds CORS (from `CAREER_CORS_ORIGINS`), rate limiting
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
