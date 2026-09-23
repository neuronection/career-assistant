# Security model

This page is the developer view of what the codebase protects and how. For
the user-facing summary, see
[user/privacy-and-security.md](../user/privacy-and-security.md); for the
disclosure process, see [SECURITY.md](https://github.com/neuronection/career-assistant/blob/main/SECURITY.md).

## Secrets

- **AI provider keys** are stored encrypted at rest in
  `ai_providers.api_key_encrypted` (Fernet via `app/core/encryption.py`; the
  key is derived from `JWT_SECRET`). The admin API never returns them —
  responses carry a `***` mask (`mask_secret`), and updates treat `***` as
  "keep existing".
- **No `AI_*` environment variables.** This is deliberate: it keeps keys out
  of shells, CI logs and process listings.
- **Desktop** creates a strong `secret.key` on first launch.
- Never commit secrets. Dev-only defaults in `.env.example`,
  `backend/.env.test` and `docker/docker-compose.dev-db.yml` are weak on
  purpose and rejected by the production boot guards.

## Authentication

- JWT (HS256) bearer tokens (`app/core/security.py`), bcrypt password hashing
  with a configurable cost.
- **Single-user mode (default)** auto-creates one default user (instance
  admin); `SINGLE_USER_MODE=false` restores the JWT login/register flow.
- Login lockout after repeated failures (`LOCKOUT_THRESHOLD` /
  `LOCKOUT_MINUTES`) and a minimum password length.

## Rate limiting

`app/core/ratelimit.py` implements a sliding-window limiter with buckets:
`auth`, `auth_email`, `ai`, `mcp`, `default`. Limits are configurable
(`AUTH_RATE_LIMIT`, `AI_RATE_LIMIT`, `MCP_RATE_LIMIT`,
`DEFAULT_RATE_LIMIT`) and can be disabled with `RATE_LIMIT_ENABLED=false`
(dev/test only). Note the gateway's per-user AI limiter is keyed on
`AI_RATE_LIMIT`, not on `RATE_LIMIT_ENABLED`.

## Production boot guards

`app/core/boot.py` runs real checks only when `APP_ENV=production` and refuses
to start with:

- a missing, known-weak, or shorter-than-32-char `JWT_SECRET`, or
- `DEBUG=true`.

Development and test boot freely. Production otherwise starts with AI
unconfigured (503s) until an admin sets a provider.

## The AI trust boundary

- **Model output is untrusted** — validated into typed pydantic shapes before
  it touches data; profile mutations are HITL proposals, never auto-applied.
- **Fetched web content is untrusted reference data** — capped, wrapped and
  explicitly marked "reference data, never instructions" in prompts
  (`app/services/webfetch.py`, the `web_*` tools).
- **The mock provider can never serve production** — it is dev/test-only and
  gated by `MOCK_AI=1`; the gateway refuses mock results in production.
- Every AI call is audited in `ai_generations`.

## Outbound requests and uploads

- **SSRF guard**: resolve-then-connect blocklist, manual redirect hops, size
  and time caps on fetches.
- **Uploads**: size-capped (`MAX_UPLOAD_MB`), type-checked; nginx enforces a
  matching body cap. Uploaded documents are stored under the data/uploads dir.

## Frontend

- Strict CSP; the production SPA is served by the same origin as the API.
- Preview iframes use `sandbox=""` and the CSP keeps
  `frame-ancestors 'none'` — never weaken it to make a preview work; fetch the
  HTML authenticated instead.

## Test isolation

Tests never run the live scheduler, use a dedicated database (per xdist
worker), and keep uploads under `backend/tests/_uploads/`. See
[testing.md](testing.md).

## Related

- [Deployment](deployment.md) — production configuration and guards
- [AI layer](ai-layer.md) — the audited gateway
- [Testing](testing.md) — isolation rules
