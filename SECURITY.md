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
- **Auth** uses JWT (HS256) bearer tokens. Boot guards
  (`app/core/boot.py`) refuse to start in `APP_ENV=production` with a weak
  or default `JWT_SECRET` or with `DEBUG=true`.
- **Known dev-only defaults** (`.env.example`, `backend/.env.test`,
  `docker/docker-compose.dev-db.yml`) intentionally ship weak values like
  `matchjob_dev_pw` and `dev-only-change-me`. They are valid only for
  localhost Docker (ports bound to `127.0.0.1`) and are rejected by the
  production boot guards. Do not reuse them in any real deployment.

## Out of scope

- Vulnerabilities in third-party services you connect yourself (your OpenAI
  provider account, your Postgres host, your reverse proxy).
- Reports from automated scanners without a demonstrated impact.
- The `mock` AI provider — it exists solely for offline development and tests.

## Supported versions

Only the latest `master` branch receives security fixes. Deployments should
track it or pin to the latest tagged release.
