# Privacy and security

Career Assistant is **self-hosted by design** — your database, your documents,
your keys. There is no managed cloud, and nothing phones home. The only
traffic that leaves is the AI calls you configure yourself.

## Where your data lives

- **Desktop app:** under your OS data directory — the SQLite database,
  uploaded documents, `secret.key` and the checkpointer database.
- **Self-hosted:** the Postgres volume (`db_data`) and the uploads volume
  (`uploads_data`). Back both up (see
  [Deployment](../dev/deployment.md#backups)).

## AI provider keys

Provider API keys are **Fernet-encrypted at rest** in the database
(`ai_providers.api_key_encrypted`). The admin API never returns them —
responses show a `***` mask marker, and updates treat `***` as "keep
existing". There are deliberately **no `AI_*` environment variables** that
could leak keys into shells or CI logs.

On the desktop, a strong `secret.key` is created on first launch and used for
encryption.

## Authentication

- **Single-user mode (default):** the app never asks you to log in — a single
  default user (instance admin) is created automatically.
- **Multi-user (`SINGLE_USER_MODE=false`):** JWT (HS256) bearer tokens with
  bcrypt password hashing, a minimum password length, login lockout after
  repeated failures, and rate limiting.

## Fail-safe production mode

`APP_ENV=production` is the default. Boot guards (`app/core/boot.py`) **refuse
to start** in production with:

- a weak or default `JWT_SECRET`, or
- `DEBUG=true`.

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
