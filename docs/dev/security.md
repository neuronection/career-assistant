# Security model

This page is the developer view of what the codebase protects and how. For
the user-facing summary, see
[user/privacy-and-security.md](../user/privacy-and-security.md); for the
disclosure process, see [SECURITY.md](https://github.com/neuronection/career-assistant/blob/main/SECURITY.md).

## Secrets

- **Per-instance key family** (identity-auth §8, plan 16 P3d): three
  independent secrets — `CAREER_SESSION_KEY` (signs session JWTs),
  `CAREER_REFRESH_KEY` (signs refresh JWTs) and `CAREER_DATA_KEY`
  (Fernet, encrypts secrets at rest and never signs). Nothing is derived
  from anything else. All three are resolved through `Settings` (process
  environment or the deployment `.env`, OS env wins) — see
  `app/core/keys.py`; unpinned, the auth-kit KeyRing generates a 0600
  `auth_keys.json` in the data dir (desktop self-hosting; production
  servers pin all three — a partial pin fails closed).
- **Secrets at rest** (`app/core/encryption.py`): AI provider keys
  (`ai_providers.api_key_encrypted`), the web-tool GitHub token, the VAPID
  push private key and MCP bridge tokens are Fernet-encrypted under
  `CAREER_DATA_KEY` (`enc::` prefix). The admin API never returns them —
  responses carry a `***` mask (`mask_secret`), and updates treat `***` as
  "keep existing". Legacy plaintext rows remain readable; ciphertext that
  does not verify under `CAREER_DATA_KEY` reads as `None`.
- **The JWT-derived Fernet is retired** (plan 16 P3d/C7): migration
  `0044` wipes stored AI provider keys (re-enter them in Settings → AI
  Configuration) and re-encrypts-or-clears every other sealed value so no
  JWT-derived ciphertext remains. The legacy source is read only by that
  one-shot drain.
- **No `AI_*` environment variables.** This is deliberate: it keeps keys out
  of shells, CI logs and process listings.
- **Desktop** key material lives in the generated 0600 `auth_keys.json`
  (data dir).
- Never commit secrets. Dev-only defaults in `.env.example`,
  `backend/.env.test` and `docker/docker-compose.dev-db.yml` are weak on
  purpose and rejected by the production boot guards.

## Authentication

The family auth contract (guideline `identity-auth.md`, ADR-0013) — the
shared `neuronection-auth-kit` package is the implementation:

- **Session cookies + double-submit CSRF** (§10): `nx_access` /
  `nx_refresh` / `nx_csrf`; cookie-authenticated non-GET requests must
  echo `nx_csrf` in `X-CSRF-Token`. `Authorization: Bearer <session
  token>` (§9 user clients) is accepted alongside cookies.
- **Instance access modes** (§4): `instance_settings.auth_mode` is
  DB-authoritative and written only at initialization (`CAREER_AUTH_MODE`
  on an empty DB). Desktop entrypoints default to `open` (DIM: implicit
  owner, `/auth/desktop/exchange`, per-boot `X-Shell-Token` request
  gate); server runs `authenticated` (login/register; first user = admin).
  Unauthenticated API requests **401** — there is no anonymous fallback.
- **Token contract** (§8): key-separated HS256 SESSION/REFRESH keys
  (`CAREER_SESSION_KEY`/`CAREER_REFRESH_KEY`/`CAREER_DATA_KEY` or the
  generated `auth_keys.json`), 60-minute access tokens, rolling 7-day
  refresh families with rotation + reuse detection, bcrypt ≥12 passwords.
- **Lockout** after repeated failures (`CAREER_AUTH_LOCKOUT_THRESHOLD` /
  `CAREER_AUTH_LOCKOUT_MINUTES`) and a minimum password length (10).
- **§16 config surface** (plan 16 P3d): `CAREER_COOKIE_SECURE`,
  `CAREER_AUTH_ACCESS_TTL_MINUTES`, `CAREER_AUTH_REFRESH_TTL_DAYS`,
  `CAREER_AUTH_REFRESH_ABSOLUTE_DAYS`, `CAREER_AUTH_LOCKOUT_*`,
  `CAREER_TRUSTED_PROXY_COUNT` and `CAREER_RATELIMIT_*` are routed through
  `Settings` into the kit config (`_install_identity`), so the deployment
  `.env` file works like the process environment (OS env wins).

## Rate limiting

`app/core/ratelimit.py` implements a sliding-window limiter with buckets:
`auth`, `auth_email`, `ai`, `mcp`, `default`. Limits are configurable
(`CAREER_RATELIMIT_AUTH`, `CAREER_RATELIMIT_AUTH_EMAIL`,
`CAREER_RATELIMIT_AI`, `CAREER_RATELIMIT_MCP`, `CAREER_RATELIMIT_DEFAULT`;
the unprefixed legacy names still work) and can be disabled with
`CAREER_RATELIMIT_ENABLED=false` (dev/test only). Note the gateway's
per-user AI limiter is keyed on the `ai` bucket, not on the enable flag.
Client identity trusts only explicitly forwarded hops
(`CAREER_TRUSTED_PROXY_COUNT`, default 0 — set 1 behind a reverse proxy;
the kit's auth limiters use the same knob).

## Production boot guards

`app/core/boot.py` runs real checks only when `APP_ENV=production` and refuses
to start with:

- a weak, partial or missing key family — all three of
  `CAREER_SESSION_KEY` / `CAREER_REFRESH_KEY` / `CAREER_DATA_KEY` pinned
  strong on a production server (missing is allowed only on desktop, where
  the generated 0600 `auth_keys.json` is the §8 key source),
- a `CAREER_DATA_KEY` that is not 32-byte urlsafe-base64 Fernet material,
- `DEBUG=true` or `DEMO_MODE=true`.

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
