# Privacy and security

Career Assistant is **self-hosted by design** — your database, your documents,
your keys. There is no managed cloud, and nothing phones home. The only
traffic that leaves is the AI calls you configure yourself.

## Where your data lives

- **Desktop app:** under your OS data directory — the SQLite database,
  uploaded documents, the per-instance key file `auth_keys.json` and the
  checkpointer database.
- **Self-hosted:** the Postgres volume (`db_data`) and the uploads volume
  (`uploads_data`). Back both up (see
  [Deployment](../dev/deployment.md#backups)).

## AI provider keys

Provider API keys are **Fernet-encrypted at rest** in the database
(`ai_providers.api_key_encrypted`). The admin API never returns them —
responses show a `***` mask marker, and updates treat `***` as "keep
existing". There are deliberately **no `AI_*` environment variables** that
could leak keys into shells or CI logs.

Encryption uses a dedicated per-instance `CAREER_DATA_KEY` (identity-auth
§8) — an independent secret that never signs anything and is never derived
from any other key. On the desktop a strong key family (`auth_keys.json`)
is created on first launch; on servers you pin all three `CAREER_*_KEY`
secrets in the environment. Older releases encrypted with a key derived
from `JWT_SECRET`; migration `0044` retires that ciphertext (AI provider
keys are wiped once and re-entered in Settings → AI Configuration).

## Authentication

Family auth contract (identity-auth, ADR-0013):

- **Desktop (`open` mode):** no login — the app boots straight into your
  data; the security boundary is your user account + data directory.
- **Web (`authenticated` mode):** sign in with email + password — session
  cookies (httpOnly + SameSite) with double-submit CSRF, bcrypt password
  hashing, a minimum password length, login lockout after repeated
  failures, and rate limiting. Access tokens live 60 minutes; refresh
  sessions rotate and can be revoked per device.
- **Self-service registration is a per-deployment switch.** The
  environment flag `CAREER_REGISTRATION_ENABLED` (default `true`; set it
  in the deployment environment or the `.env` file) controls
  `POST /auth/register`. With it off, registration answers `403` and the
  login screen hides its register action — admins create accounts from
  Settings → Users instead. On any instance the first registered user
  becomes the admin.
- **Account self-service** ([Settings → Account](settings.md#account-settingsaccount)):
  the device list behind your session with per-device sign-out, password
  change (you stay signed in, every other device is signed out) and
  account deletion — confirmed with your password, cascading to
  everything you own.

## Fail-safe production mode

`APP_ENV=production` is the default. Boot guards (`app/core/boot.py`) **refuse
to start** in production with:

- a weak, partial or missing key family (`CAREER_SESSION_KEY` /
  `CAREER_REFRESH_KEY` / `CAREER_DATA_KEY` — production servers pin all
  three long random values; desktop generates its own on first run), or
- `DEBUG=true` or `DEMO_MODE=true`.

This is intentional. The dev-only defaults in `.env.example` and the dev
compose file are valid only for localhost and are rejected by the production
guards.

## The AI trust boundary

- **Model output is untrusted.** It is pydantic-validated into typed shapes
  before it touches your data, and profile changes are proposed as review
  cards, never auto-applied (see
  [Chat and proposals](assistant-chat.md)).
- **Fetched web content is reference data, never instructions.** The assistant
  can fetch pages and search the web, but fetched content is capped, wrapped
  as reference material and explicitly marked untrusted — it cannot redirect
  the assistant.
- **The mock provider can never serve production results.** It is dev/test
  only and opt-in via `MOCK_AI=1`.

## Full audit trail

Every AI call — task, model, tokens, output and latency — is recorded in
`ai_generations` and visible in **Settings → AI audit**. There is no side door
around the AI gateway, so the trail is complete.

## Uploads and outbound requests

- Uploads are size-capped (`MAX_UPLOAD_MB`) and type-checked; nginx enforces a
  matching body cap.
- Outbound fetches are guarded against SSRF (resolve-then-connect blocklist,
  manual redirect hops, size and time caps).
- The production SPA is served with a strict CSP; preview iframes use
  `sandbox=""` and `frame-ancestors 'none'`.

## Reporting a vulnerability

Do not open a public issue — see [SECURITY.md](https://github.com/neuronection/career-assistant/blob/main/SECURITY.md) for the
private disclosure process.

## Related

- [Settings reference](settings.md) — the AI audit page
- [Deployment](../dev/deployment.md) — production configuration and guards
- [Security model](../dev/security.md) — the developer view
