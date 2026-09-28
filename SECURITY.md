# Security Policy

## Reporting a vulnerability

Please do **not** open a public issue for security problems. Use GitHub's
[private vulnerability reporting](../../security/advisories/new) for this
repository, and include:

- A description of the issue and its impact.
- Steps to reproduce (endpoint, payload, expected vs. actual behavior).
- The commit/branch you tested against.

You can expect an initial response within a few days. Please give maintainers
a reasonable window to ship a fix before any public disclosure.

## Scope: what this codebase protects

Worth knowing before you audit or deploy:

- **AI provider API keys** are stored encrypted at rest in the database
  (`ai_providers.api_key_encrypted`, Fernet via `app/core/encryption.py`).
  The admin API never returns them — responses show a `***` mask marker, and
  updates treat `***` as "keep existing". There are deliberately no `AI_*`
  environment variables that could leak keys into shells or CI logs.
- **Secrets at rest** are encrypted under a dedicated per-instance
  `CAREER_DATA_KEY` (identity-auth §8) — an independent secret that never
  signs tokens and is never derived from any other key. Token signing uses
  the separate `CAREER_SESSION_KEY` / `CAREER_REFRESH_KEY`.
- **Auth** uses JWT (HS256) session cookies + CSRF. Boot guards
  (`app/core/boot.py`) refuse to start in `APP_ENV=production` with a weak,
  partial or missing key family (`CAREER_SESSION_KEY` /
  `CAREER_REFRESH_KEY` / `CAREER_DATA_KEY`) or with `DEBUG=true`.
- **Known dev-only defaults** (`.env.example`, `backend/.env.test`,
  `docker/docker-compose.dev-db.yml`) intentionally ship weak values like
  `career_dev_pw` and `dev-only-change-me`. They are valid only for
  localhost Docker (ports bound to `127.0.0.1`) and are rejected by the
  production boot guards. Do not reuse them in any real deployment.

## Out of scope

- Vulnerabilities in third-party services you connect yourself (your OpenAI
  provider account, your Postgres host, your reverse proxy).
- Reports from automated scanners without a demonstrated impact.
- The `mock` AI provider — it exists solely for offline development and tests.

## Threat model

Career Assistant is a **dual-mode product** (family identity class D):
a local-first desktop app (`python -m careerassistant app`, pywebview
shell) and a self-hosted web deployment (docker / uvicorn). The family
identity & auth standard (identity-auth §20) defines the surfaces
below; this table is career's single source of truth for the answers
and pairs with [docs/dev/security.md](docs/dev/security.md).

| Surface | Answers for this repo |
|---|---|
| Auth surface | Unauthenticated (the auth-kit's §12 routes plus exempt product surfaces): `POST /api/v1/auth/register` (403 while `CAREER_REGISTRATION_ENABLED=false`; first user becomes admin), `/login`, `/refresh` (valid refresh cookie or Bearer refresh), `/demo` (404 unless `demo_mode=true`), `/desktop/exchange` (mounted only in desktop + `auth_mode=open`; requires the per-boot `X-Shell-Token`); plus `GET /api/v1/instance/config` (public facts only: `demo_mode`, `auth_mode`, `registration_enabled`), `/health`, `/docs` + `/openapi.json`, `/api/v1/shell/rendered`, and the static SPA. Everything else under `/api/` 401s in the kit's `SessionAuthMiddleware` — cookie or `Authorization: Bearer` session token (`WWW-Authenticate` on the 401); `local-boot`/`demo` tokens are rejected unless the live instance state admits them. The mounted MCP server (`/mcp`) authenticates with its own locally generated bearer token (`mcp_token.json`, 0600 in the data dir, bound to one user, re-read on every verify so rotation is live) and has its own rate bucket. Rate limits: two in-process sliding-window layers — the kit's per-IP + per-email auth limiters on register/login/refresh, and `RateLimitMiddleware` (`auth` + `default` buckets over `/api/`); 429 + `Retry-After`, ceilings under `CAREER_RATELIMIT_AUTH` / `_AUTH_EMAIL` / `_AI` / `_MCP` / `_DEFAULT` (+ `CAREER_RATELIMIT_ENABLED`), per-IP identity from the rightmost `CAREER_TRUSTED_PROXY_COUNT` `X-Forwarded-For` hops (default 0 = direct socket address — a client-supplied XFF is never believed; the compose stacks set 1). Lockout: 5 consecutive failures ⇒ 423 for 15 min (`CAREER_AUTH_LOCKOUT_THRESHOLD` / `_MINUTES`), generic `Invalid email or password`, dummy-hash verify against timing enumeration; passwords ≥ 10 chars, bcrypt. |
| Instance mode | `auth_mode` / `demo_mode` are rows in `instance_settings` — DB is authoritative, resolved per request through the kit's live instance state, unknown value fails closed to `authenticated`. `CAREER_AUTH_MODE` / `CAREER_DEMO_MODE` are consumed **only** when initializing an empty DB (`app/auth/instance.py`): desktop defaults to `open`, server to `authenticated`; `open` on a server entrypoint is never legal (§4.4 — clamped loudly at init). Post-init env flips are ignored with a loud warning. Runtime changes: `PATCH /api/v1/admin/instance` only — admin + current-password re-verification, §4.5 transitions, audited `admin.instance_transition`; `authenticated → open` is refused on server entrypoints, needs explicit confirmation + the current password, is refused while other user rows exist, and revokes every session. `demo_mode` has no runtime API. A copied/restored DB keeps its mode, users, and settings; token keys never live in the DB, so a bare DB copy cannot mint tokens. The production boot guard aborts on `CAREER_DEMO_MODE=true` (`app/core/boot.py`, §13); the demo compose runs `APP_ENV=demo` and never production. |
| Session storage | The kit's §10 cookie triple: `nx_access` (`__Host-nx_access` when `CAREER_COOKIE_SECURE=true`, i.e. TLS), `nx_refresh` (Path `/api/v1/auth`), `nx_csrf` (JS-readable). Access/refresh are HttpOnly + SameSite=Lax (+ `Secure` under TLS); access 60 min default (`CAREER_AUTH_ACCESS_TTL_MINUTES`, 24 h kit cap), refresh 7-day rolling / 30-day absolute (`CAREER_AUTH_REFRESH_TTL_DAYS` / `_ABSOLUTE_DAYS`), rotated on every use — replay of a rotated `jti` revokes the whole family + bumps `token_version` (423); the `ver` claim must equal `users.token_version`. CSRF: double-submit — non-GETs carrying an auth cookie must echo `nx_csrf` in `X-CSRF-Token` (403); no tokens in localStorage. Revocation paths: `POST /auth/logout` (one family), `/auth/logout-all` (+ `token_version` bump), `DELETE /api/v1/me/sessions/{id}`, admin `PATCH /users/{id}` + `POST /users/{id}/force-logout` (bump), `DELETE /api/v1/me` (cascade), and the `authenticated → open` transition. Non-browser clients present the session token as `Authorization: Bearer` (§9 user-client class — the kit's enforcement accepts it everywhere, not just the auth routes). DIM (`open` desktop) mints a `local-boot` session only — no refresh family; every boot exchanges anew through `/auth/desktop/exchange`. |
| Trust boundaries | **Shell ↔ backend (ADR-0010 shape):** the pywebview window loads the SPA from `127.0.0.1` on a random port (`app/shell.py`); in desktop mode every API request must carry the per-boot `X-Shell-Token` (process-memory secret, regenerated each boot — `app/desktop/shell_token.py`), and the `?shell=<token>` query marks only that document for the desktop CSP variant (`unsafe-eval` for the pywebview bridge); browsers never see the token and keep the strict web CSP (`SecurityHeadersMiddleware`: nosniff, `X-Frame-Options: DENY`, strict referrer policy, CSP with `script-src 'self'`). **User ↔ agent tools (ADR-0011):** model output is untrusted input — every provider call goes through the audited `app/ai/gateway.py`; chat tools are read-only or propose-first (profile edits arrive as HITL proposal cards per ADR-0015, never direct writes); the MCP resource server's tools are read-scope with their own token + rate limits. **Client ↔ server:** cookie sessions + CSRF, deny-by-default CORS (`CORS_ORIGINS`; empty in the compose stacks = same-origin only), the SSE notification stream is session-authenticated and subscribed per user id (no WebSocket surface). **Device ↔ integration API:** none — career has no machine-credential transport (health's); provider/search traffic is outbound-only with keys decrypted from the DB at call time. |
| Data isolation | No tenants. Every domain row is reachable from exactly one `(user, profile)`: `user_id` FKs with DB-level `ON DELETE CASCADE` (career keeps its user_id FKs; the person-being-coached JSON sections live on the `profiles` row, 1:N since P3b). `X-Profile-Id` is ownership-bound per §15 in `ProfileBindingMiddleware`: server — absent ⇒ 400, malformed/unknown/cross-user ⇒ 403 (no silent default in web mode); desktop — falls back to the last-used profile (Default fallback) and an explicit header touches `last_used_at`. Profile-independent surfaces (`/auth`, `/me`, `/profiles`, `/admin`, `/instance`, health, shell) work without the header. Out-of-ownership domain resources answer a hidden **404** so existence never leaks; **403** is reserved for binding/permission violations; **401** means unauthenticated. Deleting the last profile re-provisions Default (§6). |
| Secrets at rest | Three independent per-instance keys (§8, `app/core/keys.py`): `CAREER_SESSION_KEY` (signs session JWTs) / `CAREER_REFRESH_KEY` (signs refresh JWTs) / `CAREER_DATA_KEY` (Fernet — encrypts secrets at rest, never signs). No key is derived from another (the legacy JWT-derived Fernet is retired — migration `0044` drained its ciphertext and wiped stored provider keys for re-entry); all-three-or-none pinning (a partial pin fails closed at keyring resolution *and* boot); production refuses weak (<32 chars), known dev values, duplicates, and non-Fernet DATA_KEY material, and requires the family pinned on servers (`app/core/boot.py`); desktop generates a 0600 `auth_keys.json` in the data dir. AI provider keys live only as `ai_providers.api_key_encrypted` under `DATA_KEY` — admin responses mask (`***` = keep existing), there are deliberately no `AI_*` env vars; the GitHub token, VAPID push keys, and MCP bridge tokens are sealed the same way. A disk thief with the data dir **and** the key material (env/.env or `auth_keys.json`) gets the DB (bcrypt hashes, decryptable sealed secrets) and can forge sessions; backups (`pg_dump` + upload tars) carry the sealed rows but not `CAREER_DATA_KEY` — protect them like the database, and the `.env` like a key. |
| Audit | `audit_events` (append-only) through the kit's audit sink (`CareerAuditSink`): `auth.register`, `auth.login` (ok/denied), `auth.refresh` (incl. reuse-denied), `auth.logout` / `auth.logout_all`, `auth.desktop_exchange`, `auth.demo_login`, `auth.session_revoke`, `auth.password_change`, `auth.account_delete`, `admin.user_update`, `admin.password_reset`, `admin.force_logout`, `admin.instance_transition` — actor, action, resource, outcome, timestamp. Separately, the AI trail (`ai_generations`, viewable at `/api/v1/admin/ai/generations`) records task, provider/model, token counts, latency, and status for every gateway call. Domain reads/writes (profiles, CVs, experiences, chats, postings) are **not** audited — that is health's §17 extension. No API endpoint edits or deletes audit rows; the trail can only be erased by direct database access or backup-retention expiry. |
| Admin surface | Server: the **first registered user becomes admin** — race-guarded (`CareerUserStore.create` serializes creation under a lock; Default profile provisioned in the same transaction). On a fresh public deployment, register first or set `CAREER_REGISTRATION_ENABLED=false` before exposing the port. Afterwards only admins promote/demote (`PATCH /api/v1/admin/users/{id}`; guard rails: no self-demotion/self-deactivation, no demoting the last admin, `token_version` bump on change). Desktop `open`: the implicit owner (`owner@local`, password-less until `open → authenticated`) is the admin. The UI is the family-shared `AdminUserTable` (`@neuronection/assistant-ui`, Settings → Users) listing users with **activity counts = match insights per user** (`CareerUserStore.activity_counts`) and the full action bar. Career's own `/admin/*` routes (catalog moderation, AI audit viewer, posting sources, system schedules) sit behind `require_admin` and transcend ownership for shared-catalog moderation. Blast radius: reset any password, force-logout anyone, deactivate accounts, flip instance `auth_mode` (password re-verified), and moderate the shared job/path/skill catalog. |
| Deployment exposure | **Desktop:** `127.0.0.1` on a random port + per-boot shell secret; the OS user's data dir is the security boundary. **Web:** `docker-compose.standalone.yml` (db + app + nginx; `--profile backup` adds the scheduled `pg_dump` sidecar writing `./backups` with retention) and `docker-compose.prod.yml` (app + db behind your own proxy); the app container publishes no host ports — nginx routes everything; both stacks set `CAREER_TRUSTED_PROXY_COUNT=1` (proxy-fronted by design). The shipped `nginx.conf` is **HTTP-only** (loopback/VPN/dev) — internet-facing deployments must mount `nginx-TLS.conf` (certbot webroot ACME + HSTS) and set `CAREER_COOKIE_SECURE=true`. Backups are unencrypted `pg_dump -Fc` + upload tars; the restore drill is documented in [docs/dev/deployment.md](docs/dev/deployment.md) — keep copies off-machine and protect them like the database. **Demo:** `docker-compose.demo.yml` — its own compose project and networks, PostgreSQL `neuro_career_demo`, `demo-net` is `internal: true` (no container egress — AI/web-import stay dark), only the edge gateway publishes a port (default `127.0.0.1`, `DEMO_BIND` to move it behind a tunnel), registration disabled, and a one-shot `demo-seed` service running the guarded `scripts/seed-demo.py` (refuses any target that is not a `*_demo` database / explicit `--demo-dir` on a `demo_mode=true` instance; `--profile reset` re-seeds pristine); `GET /api/v1/instance/config` feeds the persistent "Demo — synthetic data" badge pre-login, and `APP_ENV=demo` means a production entrypoint can never boot this config. |

Known gaps (documented, not papered over): domain reads/writes beyond
the identity/admin surface are not audited (no `audit_events` for
profile/CV/chat/posting access — only the AI generation trail); there
is no second factor (no MFA/passkeys; OIDC delegation §14 is reserved
but unimplemented — a single password protects an account); the rate
limiters are in-process sliding windows, so a multi-replica deployment
would need shared counters (documented in `app/core/ratelimit.py`); and
the desktop `?shell=` CSP variant grants `unsafe-eval` on the
shell-token-marked document only — a compromised pywebview JS context
that exfiltrates the boot token widens CSP for that boot (token and
CSP both die on restart).

## Supported versions

Only the latest `main` branch receives security fixes. Deployments should
track it or pin to the latest tagged release.

## Dependency licensing baseline

- All runtime dependencies are permissively licensed (MIT / BSD / Apache-2.0
  / PSF / MPL-2.0) with one documented exception: **psycopg 3**
  (`psycopg`, `psycopg-binary`, `psycopg-pool`) is LGPL-3.0-only. It is the
  Postgres driver required by the LangGraph Postgres checkpointer, is used
  unmodified as a pip-installed library, and its LGPL obligations attach to
  the library itself. This is an accepted, reviewed dependency (no GPL-family
  code is copied into this codebase); revisit if the checkpointer gains a
  permissively-licensed driver option.
