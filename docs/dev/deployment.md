# Deployment Guide

Self-hosting Career Assistant. Two supported paths:

- **Server operators (recommended):** the **source-free release bundle** —
  `career-compose-vX.Y.Z.tar.gz` from the GitHub release, images pinned by
  digest, installed by `scripts/install.sh` inside the bundle. No source, no
  build toolchain on the host.
- **Developers / source checkouts:** the compose stack built from a clone —
  `scripts/run-docker.sh` (first deploy) and `scripts/update-docker.sh`
  (refresh), as documented below.

The stack implements the family deployment contract: one-shot `migrate` + `serve` entrypoint modes,
split owner/app DB credentials, `/health` + `/ready` probes, scheme-derived
cookies, and off-host-capable backups with a run ledger.

---

## Server install from a release bundle

Prerequisites: a Linux host (Ubuntu 22.04/24.04 reference) with **Docker +
Docker Compose v2**, ≥ 4 GB RAM, ~5 GB free disk, a non-root user in the
`docker` group. The installer never runs as root, never installs packages,
never overwrites an existing `docker/.env`.

One-liner (the bootstrap resolves the latest release, verifies the bundle
SHA-256, extracts and hands off to the audited in-bundle installer):

```bash
curl -fsSL https://neuronection.com/install/career.sh | bash
# cautious form: download it, read it, then run it
curl -fsSL https://neuronection.com/install/career.sh -o career-bootstrap.sh
less career-bootstrap.sh
bash career-bootstrap.sh --dir ~/career-assistant
```

Bootstrap flags: `--dir DIR`, `--ref vX.Y.Z` (pin an exact release),
`--dry-run` (resolve + verify + print, write nothing), `--offline
career-compose-vX.Y.Z.tar.gz` (already-downloaded bundle, no network
download), and `--` to forward installer flags — e.g.
`-- --http-port 8092` or `-- --integrations-dir /srv/career/integrations`. The one-liner URL 302-redirects to the GitHub
release asset (trust anchor = the release, not the website); until that
route is published, use the asset from the release page.

Manual, without the bootstrap:

```bash
# from the release: career-compose-vX.Y.Z.tar.gz + manifest.json + SHA256SUMS
sha256sum -c SHA256SUMS
mkdir -p ~/career-assistant
tar -xzf career-compose-vX.Y.Z.tar.gz -C ~/career-assistant
cp manifest.json ~/career-assistant/          # installer pins the image digest from it
cd ~/career-assistant
bash scripts/install.sh
```

What `scripts/install.sh` does (see [docker/README.md](../../docker/README.md)
for the full flag table): generates `docker/.env` from the example with
fresh secrets (`umask 077`, never printed, never overwritten on a re-run) →
pins `CAREER_IMAGE` from the release manifest (the bootstrap forwards
`--image app=<digest>`; priority: `--image [KEY=]REF` > `--image-tag` >
`$CAREER_IMAGE` > manifest > existing `.env`) → sets `HTTP_PORT` →
optionally configures the **operator feeder** (a first install asks once,
default No; `--integrations-dir PATH` / `--no-integrations` decide it
non-interactively — it writes `docker/docker-compose.integrations.yml` plus
the two `CAREER_EXTENSION_*` values) →
pre-flights published ports → pulls → `up -d` → waits for `/health` →
prints the URL and the first-admin note. Exit codes: `0` ok · `1`
usage/prereq · `2` image pull · `3` compose config/start or health · `4`
port conflict.

Port plan: the bundle publishes one host port (`HTTP_PORT`, default 80).
Multiple Neuronection stacks on one host get distinct ports
(`--http-port 8090/8091/8092` for health/study/career).

### Updating a bundle install

1. Read the release notes; take a backup (`scripts/backup.sh` — off-host
   destination via `BACKUP_REMOTE`).
2. Download the new release's bundle + `manifest.json` + `SHA256SUMS`.
3. Extract over the install directory — `docker/.env` is not in the
   bundle, so secrets and settings survive; copy the new `manifest.json` in.
4. `bash scripts/update.sh` — bumps `CAREER_IMAGE` to the new manifest
   digest, pulls, `up -d`, waits for `/health`. The previous pin is kept
   (a comment in `docker/.env` + the printed rollback command) and no
   destructive data operation ever runs.

Rollback: `bash scripts/update.sh --image <previous pin>` (recorded in
`docker/.env`), and restore the pre-upgrade dump with
`scripts/restore.sh` if the release migrated the schema — pre-1.0 there is
no downgrade path, so keep the previous bundle and a backup before every
update.

## Quick start (Docker Compose)

Prerequisites: Docker + Docker Compose v2, a machine with ports 8100 (or your
choice) reachable, or ports 80/443 for the optional proxy.

```bash
git clone https://github.com/neuronection/career-assistant.git
cd career-assistant

cp docker/.env.production.example docker/.env
# Edit docker/.env — set the three CAREER_*_KEY secrets and both DB passwords
# (CAREER_DB_OWNER_PASSWORD, CAREER_DB_PASSWORD)
# and the two split DB secrets (long random values; generate each key
# separately)

docker compose -f docker/docker-compose.prod.yml up -d --build
```

The app is on `http://<host>:8100`. Schema changes run in the **one-shot
`migrate` service** (it provisions the database as the owner role and
exits); the app service starts only after migrate completed successfully
and never runs DDL itself. For a single-host stack with bundled nginx
(TLS-ready) use `docker/docker-compose.standalone.yml` instead — see *TLS
with the bundled nginx* below. First-time deploys can also use
`./scripts/run-docker.sh`; existing installs refresh via
`./scripts/update-docker.sh`.

### Credential split

Two DB roles, two secrets:

| Role | Used by | Env |
|---|---|---|
| **owner** (DDL) | the one-shot `migrate` service only | `CAREER_DB_OWNER_PASSWORD` → `CAREER_MIGRATIONS_DATABASE_URL` |
| **app** (DML only) | the web app | `CAREER_DB_PASSWORD` → `CAREER_DATABASE_URL` |

The app container never receives the owner DSN or password, so a leaked app
container cannot `CREATE` or `DROP` anything. `migrate` provisions the app
role (`CAREER_DB_APP_USER`, default `neuronection_career_app`), its grants
and default privileges, the `vector` extension, the LangGraph checkpoint
schema, every known vector space, and the Alembic chain — then re-grants
and verifies (the job fails loudly if the app role could DDL). Leaving both
Both split passwords are required by the compose path (`:?` guards); there is
no fallback to a shared password. Legacy single-role installs omit the split
marker and boot with a loud warning at serve time.

### Readiness vs liveness

- `GET /health` — liveness: 200 unless the process is broken (degraded-open
  storage details ride the payload).
- `GET /ready` — readiness: 200 only after boot completed, the database is
  reachable **at this release's Alembic head** (the migrate job finished),
  and required object storage is available. Anything else is a `503`, so a
  proxy/monitor pulls a half-migrated or still-booting instance out of
  rotation. Soft signals (optional storage degradation, Redis) never flip
  it. Both routes are exposed through the bundled nginx.

### First boot walkthrough

1. **Register the admin** — the web deployment runs the family
   `authenticated` instance mode (identity-auth §4): the first boot shows
   the login screen, register the first user (it automatically becomes
   the admin). The desktop app (`python -m careerassistant`) runs `open`
   instead — no login at all (Desktop Identity Mode, implicit local
   owner). Modes are set once on an empty database (`CAREER_AUTH_MODE`)
   and are DB-authoritative afterwards.
2. **Load the job catalog** (the app ships none): open the empty catalog
   page as the admin and use **Load the official catalog** (sync → approve →
   apply), or add an uploaded/official pack under Settings → Data providers.
   For a bare-metal dev/demo database, `./scripts/seed.sh` also installs the
   pinned fixture copy; `python -m careerassistant migrate` registers the
   official tiles but never fetches or applies them.
3. **Configure AI** — Settings → Instance AI Configuration (admin) or My AI
   Configuration (personal). A fresh production install starts unconfigured:
   AI endpoints answer `503` until the caller's personal provider or an
   instance provider is configured (OpenAI, OpenRouter, or a local
   Ollama/LM Studio via an OpenAI-compatible base URL). There are deliberately
   no `AI_*` env vars.
4. Onboard your profile and start exploring.

### Configuration reference (docker/.env)

| Variable | Required | Default | Notes |
|---|---|---|---|
| `CAREER_SESSION_KEY` / `CAREER_REFRESH_KEY` / `CAREER_DATA_KEY` | yes | — | The per-purpose key family (identity-auth §8): session-JWT signing / refresh-JWT signing / Fernet for secrets at rest. Three **independent** secrets, all three or none (partial pins fail closed) — generate each with `python3 -c 'import secrets; print(secrets.token_urlsafe(32))'`. Never derived from each other. |
| `CAREER_TRUSTED_PROXY_COUNT` | no | `1` (compose) | Rightmost `X-Forwarded-For` hops trusted for per-IP limits (§7/§16). The compose stacks are proxy-fronted by design; keep `1` behind one proxy, `0` for direct exposure. |
| `CAREER_COOKIE_SECURE` / `CAREER_PUBLIC_URL` / `CAREER_TLS` | no | derived | Cookie `Secure` **derives from the public scheme** (deployment contract): set `CAREER_PUBLIC_URL=https://…` (Secure on) or `http://…` (off, so LAN/VPN login works); `CAREER_TLS=1` is the no-domain escape hatch. An explicit `CAREER_COOKIE_SECURE=true\|false` overrides both. Never hard-coded `true`. |
| `CAREER_AUTH_MODE` | no | `authenticated` | Init-only instance mode (`open` is desktop-only and refused on server). Post-init flips are ignored. |
| `CAREER_REGISTRATION_ENABLED` | no | `true` | Disable to close the public registration route. |
| `CAREER_AUTH_ACCESS_TTL_MINUTES` / `CAREER_AUTH_REFRESH_TTL_DAYS` / `CAREER_AUTH_REFRESH_ABSOLUTE_DAYS` | no | `60` / `7` / `30` | Session lifetimes (identity-auth §8). |
| `CAREER_AUTH_LOCKOUT_THRESHOLD` / `CAREER_AUTH_LOCKOUT_MINUTES` | no | `5` / `15` | Login brute-force lockout (§7). |
| `CAREER_RATELIMIT_AUTH` / `_AUTH_EMAIL` / `_AI` / `_MCP` / `_DEFAULT` | no | `10` / `30` / `30` / `120` / `240` | Per-bucket rate ceilings, requests/minute (`0` disables a bucket). |
| `POSTGRES_PASSWORD` | legacy only | — | Legacy alias accepted by host backup/restore when `CAREER_DB_OWNER_PASSWORD` is unset; compose does **not** use it to bootstrap the DB. |
| `CAREER_DB_OWNER_PASSWORD` / `CAREER_DB_PASSWORD` | yes | — | Distinct owner/app secrets (credential policy): the owner bootstraps the DB and is used by `migrate` only; the app connects with the DML-only app role. Generate each separately. |
| `CAREER_DB_APP_USER` | no | `neuronection_career_app` | The DML-only app role name `migrate` provisions. |
| `CAREER_MIGRATIONS_DATABASE_URL` | migrate only | *(composed)* | The explicit owner-DSN seam; the compose `migrate` service composes it from `POSTGRES_USER` + `CAREER_DB_OWNER_PASSWORD`. Never set it on the app. |
| `CAREER_DB_SPLIT` | migrate only | `1` (compose) | Owner-side split marker (credential policy, three states): with the migrations URL = supported split; without it = **refuse to boot**; absent = legacy single-role (loud warning in production). |
| `CAREER_DB_APP_ROLE` | app only | `1` (compose) | Serving-side marker: selects split semantics without requiring the owner URL. |
| `POSTGRES_DB` / `POSTGRES_USER` | no | `neuronection_career` / `neuronection_career_owner` | Database name/user (family datastore naming). |
| `CAREER_API_PORT` | no | `8100` | Host port the app publishes on. |
| `CAREER_MAX_UPLOAD_MB` | no | `25` | Per-upload cap (university PDFs, CVs, photos) enforced by the upload service. |
| `CAREER_EXPORT_MAX_MB` | no | `1024` | Data-export ceiling (1–1024 MB), independent of the upload cap. The store's per-object cap binds to `max(upload, export)` when `CAREER_OBJECT_STORAGE_MAX_MB` is unset. |
| `CAREER_CLOUD_PROFILE` / `CAREER_OBJECT_STORAGE_BACKEND` | no | *(empty)* / `local` | `aws`/`azure`/`gcp`/`cloud` plus `s3`/`azure_blob` for provider storage. Leave both empty for the mounted uploads volume. Combine `docker-compose.cloud.yml` for a cloud deployment; see [storage.md](storage.md). |
| `CAREER_CORS_ORIGINS` | no | *(empty)* | Only needed if you serve the SPA from a different origin than the API. |
| `CAREER_IMAGE` | no | `career-assistant:local` | Deploy a pre-built registry image (e.g. `ghcr.io/neuronection/career-assistant:vX.Y.Z`) instead of building. |
| `HTTP_PORT` | standalone | `80` | Host port the bundled nginx publishes on (standalone flavor). |

### TLS with the bundled nginx (standalone flavor)

Point a DNS A/AAAA record at the host, then use the standalone stack:

```bash
docker compose -f docker/docker-compose.standalone.yml up -d --build
```

By default it serves HTTP on port 80 — fine for VPN/loopback only, and the
derived cookies stay `Secure`-off so login works (deployment contract). For
internet-facing TLS: set `SERVER_NAME` in `docker/nginx-TLS.conf`, provide
certs at `docker/certs/{fullchain,privkey}.pem` (certbot webroot renewals
answer on port 80), uncomment the TLS volumes and the `443:443` mapping in
the compose file, and swap the mounted conf to `nginx-TLS.conf`. Then make
the cookies derive the public scheme: set `CAREER_PUBLIC_URL=https://…` (or
`CAREER_TLS=1`) in `docker/.env` — session cookies flip to `Secure` without
a hard-coded value. nginx streams SSE without buffering and enforces a 64 MB
body cap (keep it ≥ `CAREER_MAX_UPLOAD_MB`).

## Upgrades

```bash
cd career-assistant
./scripts/update-docker.sh     # git pull + rebuild + restart + health-wait
```

Bundle installs (no source checkout) update differently — extract the new
release bundle over the install directory and run `bash scripts/update.sh`
(see *Updating a bundle install* above); it never rebuilds and never
touches data volumes, and it keeps the previous image pin for rollback.

Or manually: `git pull`, back up first (see Backups), then
`docker compose -f docker/docker-compose.prod.yml up -d --build`.

Schema migrations apply through the one-shot `migrate` service on every
`up`: it provisions as the owner role (app role, `vector` extension,
checkpoint schema, vector spaces), runs `alembic upgrade head`, re-grants
and verifies — while the `app` service never touches the schema. Pre-1.0
there is **no downgrade path** — pin a version tag if you need
reproducibility.

Before migrating, the entrypoint runs `python -m careerassistant
preflight` and reads the volume's `alembic_version`. A PostgreSQL volume
from before the v0.17 baseline is **not** upgradeable: the migrate service
exits non-zero with that guidance instead of a bare Alembic traceback, and
it never drops the volume for you. Recreate it with `docker compose down
-v` (this destroys the data) or keep running the previous release. The same
check runs outside the container (`python -m careerassistant preflight`)
and in `./scripts/run-dev.sh --web`.

Upgrading a pre-split install: pull the new compose files (they add the
`migrate` service), add `CAREER_DB_OWNER_PASSWORD` / `CAREER_DB_PASSWORD`
to `docker/.env` (rotate the owner password as part of this — the
one-release migration path in the credential policy), and `up -d`. The first migrate
run provisions the app role; nothing else changes for users. The serving
container is refused to boot when the split marker is set without the
migrations URL (broken tri-state, the credential policy).

`./scripts/update-docker.sh` also runs the one-time datastore
rename (`career_*` / `neuro_career_*` → `neuronection_*`) before the stack
boots — no manual step for an existing install; see
[docker/README.md](../../docker/README.md) → "Renaming …" for the guards
and the manual recipes.

Set the three `CAREER_*_KEY` secrets in `docker/.env` **before** the first
start (see the configuration reference). The v0.17 baseline never derives
key material from `JWT_SECRET`; a pre-baseline install is not upgradeable —
the entrypoint preflight refuses the old volume (see Upgrades above), so
recreate it and re-enter AI provider keys, the GitHub token, VAPID push keys
and MCP bridge tokens under `CAREER_DATA_KEY`.

## Backups

Two things hold state: the Postgres volume (`db_data`) and the uploads volume
(`uploads_data`). The product backup script handles all of it — dump,
uploads, one run row in the `backup_runs` ledger (backup policy), optional
`age` encryption, and the off-host upload:

```bash
# Local archive + ledger row (label the install non-DR if you stop here)
./scripts/backup.sh

# T1/off-host: destination + encryption in docker/.env (or the environment)
#   BACKUP_REMOTE=s3://my-bucket/career/backups     # aws s3 cp, or rclone
#   BACKUP_REMOTE=rclone:myremote:career/backups    # any rclone target
#   BACKUP_REMOTE=https://acct.blob.core.windows.net/container/path  # azcopy
#   BACKUP_AGE_RECIPIENT=age1...                    # encrypt when shared
BACKUP_REMOTE=s3://my-bucket/career/backups ./scripts/backup.sh
```

The compose `backup` sidecar (`--profile backup`) stays a same-host dump
loop and writes the same ledger rows; T1 off-host scheduling is
[backup-timer.md](backup-timer.md). — a local-only install must be
labelled **non-DR**; T1 requires the off-host leg. Check the chain:
`SELECT started_at, status, bytes, destination FROM backup_runs ORDER BY
started_at DESC LIMIT 5;` — a row older than 2× the interval means the
backup chain is broken.

Restore is a **drill, not a script**: restore into a throwaway target,
re-grant the app role, verify named counts and a known record —
[docs/dev/restore-drill.md](restore-drill.md) is the procedure and its pass
criteria. Desktop backups (`python -m careerassistant backup`) are
local-only and refuse an object backend.

Under a cloud profile the app container has **no uploads volume**: document
bytes live in the bucket/container, so the tar step does not apply and
provider durability/versioning covers them (enable versioning and a
lifecycle rule). The database dump stays the backup you schedule. Details:
[storage.md](storage.md).

## Reverse proxy (bring your own)

Any proxy works as long as it does not buffer responses (future SSE
endpoints) and allows request bodies ≥ `CAREER_MAX_UPLOAD_MB`.

**nginx**

```nginx
server {
    server_name career.example.com;
    client_max_body_size 64m;

    location / {
        proxy_pass http://127.0.0.1:8100;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_buffering off;      # SSE-friendly
    }
}
```

Add TLS via certbot. Set `--reset`-free headers per your policy; HSTS belongs
at the TLS layer.

## Bare metal (no Docker)

Python 3.12+, Node 26+, and a reachable Postgres 16:

```bash
# Build the SPA
cd frontend && npm ci && npm run build && cd ..

# Backend
cd backend
uv sync
export CAREER_APP_ENV=production
export CAREER_DATABASE_URL=postgresql+asyncpg://user:pass@127.0.0.1:5432/neuronection_career
export CAREER_SESSION_KEY="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"
export CAREER_REFRESH_KEY="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"
export CAREER_DATA_KEY="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"
uv run alembic upgrade head
uv run uvicorn app.main:app --host 0.0.0.0 --port 8100
```

The app auto-detects `../frontend/dist` and serves it — no separate web
server needed. Run under systemd (`Restart=on-failure`,
`StateDirectory=career-assistant`) and front it with nginx for TLS (set
`CAREER_TRUSTED_PROXY_COUNT=1` and derive the cookies:
`CAREER_PUBLIC_URL=https://career.example.com` or `CAREER_TLS=1`).

Bare metal is the **legacy** credential shape (credential policy, three states): one
role serves and may DDL, allowed with a loud production warning. To run the
split shape, provision first (`CAREER_MIGRATIONS_DATABASE_URL` +
`CAREER_DB_SPLIT=1` + `CAREER_DB_PASSWORD` + `python -m careerassistant
migrate`), then serve with the app-role DSN. The compose stacks do this
for you.

Boot guards: production refuses to start with a weak, partial or missing
key family (`CAREER_SESSION_KEY` / `CAREER_REFRESH_KEY` /
`CAREER_DATA_KEY`) or `DEBUG=true` — this is intentional. `CAREER_DB_SPLIT`
without a migrations URL refuses in every environment (broken tri-state).

## Troubleshooting

- **`503` on AI features** — no provider configured; see First boot
  walkthrough step 3.
- **`413` on PDF upload** — raise `CAREER_MAX_UPLOAD_MB` and your proxy body cap.
- **Container restart loop** — check logs for the boot guard message
  (`docker compose -f docker/docker-compose.prod.yml logs migrate`, then
  `… logs app`); usually a weak or missing `CAREER_*_KEY` secret, or the
  migrate job failed (the app waits for it and never serves an
  unmigrated schema).
- **`CAREER_DB_SPLIT=1` refused to boot** — the migrations URL is missing;
  set `CAREER_MIGRATIONS_DATABASE_URL` (owner DSN, migrate service only) or
  remove the marker to stay legacy (the credential policy).
- **Health checks** — `GET /health` is liveness (wire container monitors to
  it); `GET /ready` is readiness (503 while booting, before migrate
  finished, or while the DB/required storage is down). A `503` from `/ready`
  with `"checks": {"database": "behind: …"}` means the migrate job has not
  completed for this release yet.
