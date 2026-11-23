# Career Assistant - Docker Utilities & Cheat Sheet

This directory contains the Docker configuration files for Career Assistant.
It mirrors Health Assistant's docker layout (family standard).

For development on the host see the root `README.md` and `scripts/run-dev.sh`.

## File map

| File | Purpose |
|---|---|
| `docker-compose.dev-db.yml` | Dev infrastructure only: Postgres :5433 + Redis :6380 for host-based development (`scripts/run-dev.sh`). |
| `docker-compose.prod.yml` | Production services (app + one-shot migrate + Postgres). Proxy handled externally or via the standalone flavor. Supports `CAREER_IMAGE` to deploy pre-built GHCR images. |
| `docker-compose.standalone.yml` | Canonical self-hosted single-host stack: one-shot migrate + app + Postgres + nginx (TLS-ready). |
| `docker-compose.demo.yml` | Egress-blocked demo flavor: isolated project/networks, database `neuronection_career_demo`, synthetic-only data (never production). |
| `Dockerfile` | Multi-stage: frontend bundle → single uvicorn image serving API + SPA. |
| `entrypoint.sh` | Modes (deployment contract): `migrate` (one-shot provisioning as the owner: app role, `vector`, Alembic, checkpoint schema, vector spaces, re-grant) and `serve` (never runs migrations/DDL). Unknown mode fails closed. |
| `nginx.conf` | HTTP-only reverse proxy (loopback / VPN). |
| `nginx-TLS.conf` | TLS-terminating variant (certbot webroot ACME + HSTS). |
| `backup-sidecar.sh` | The `backup` profile's dump loop; each run writes a `backup_runs` ledger row (backup policy). Off-host upload lives in `scripts/backup.sh`. |
| `init-test-db.sh` / `init-test-db` | Creates the `neuronection_career_test` DB used by pytest. |

## Compose project name & volumes

Every compose file pins an explicit top-level `name:` — the Compose
project name — so volume and network prefixes are deterministic no matter
which directory `docker compose` runs from (and identical to health's and
study's layout).

| Compose file | Project (`name:`) | Volume prefix |
|---|---|---|
| `docker-compose.dev-db.yml` | `career-assistant-dev` | `career-assistant-dev_*` |
| `docker-compose.prod.yml` | `career-assistant` | `career-assistant_*` |
| `docker-compose.standalone.yml` | `career-assistant` | `career-assistant_*` |
| `docker-compose.demo.yml` | `career-assistant-demo` | `career-assistant-demo_*` |

`COMPOSE_PROJECT_NAME` (set by `scripts/worktree.sh`) still overrides the
pinned name, so concurrent worktree checkouts stay fully isolated —
containers, named volumes and the network — instead of sharing one dev DB.

**One-time adoption of the legacy `career_*` dev volumes:** Docker has no
`volume rename`, so with the dev stack down, copy each volume into a
correctly-labeled one under the new prefix, verify, then drop the old
copy (leave the final `docker volume rm` until you have checked the copy):

```bash
docker compose -p career -f docker/docker-compose.dev-db.yml down   # legacy project; volumes kept
for v in career_postgres_data career_redis_data; do
  docker volume create --label com.docker.compose.project=career-assistant-dev \
    --label com.docker.compose.volume="$v" "career-assistant-dev_$v"
done
docker run --rm --entrypoint sh -v career_career_postgres_data:/from:ro \
  -v career-assistant-dev_career_postgres_data:/to pgvector/pgvector:pg16 -c 'cp -a /from/. /to/'
docker run --rm --entrypoint sh -v career_career_redis_data:/from:ro \
  -v career-assistant-dev_career_redis_data:/to redis:7-alpine -c 'cp -a /from/. /to/'
# verify (PG_VERSION present, the neuronection_career database opens), then:
docker volume rm career_career_postgres_data career_career_redis_data
docker compose -f docker/docker-compose.dev-db.yml up -d
```

Dev databases are disposable in any case — `down -v` on the dev stack
recreates the family datastore names from scratch.

## Dev infrastructure (host-based development)

```bash
docker compose -f docker/docker-compose.dev-db.yml up -d   # Postgres :5433 + Redis :6380
./scripts/run-dev.sh                                       # backend :8100 + frontend :3100
```

The dev stack creates the family datastore names: database `neuronection_career`,
bootstrap role `neuronection_career_owner` and the companion test database
`neuronection_career_test` (per-xdist-worker databases follow
`neuronection_career_test_gwN`).

## Self-hosting (standalone flavor)

```bash
cp docker/.env.production.example docker/.env    # then edit secrets
docker compose -f docker/docker-compose.standalone.yml up -d --build
```

- App + Postgres + nginx; the app image serves API and SPA same-origin.
- **Persistent host-local state**: `career_data` (extension installs and their
  content-addressed store, retrieval data, the datastore marker) and
  `career_config` (the auth-kit key file) are named volumes at the app's
  default paths — `CAREER_DATA_DIR` / `CAREER_CONFIG_DIR` are set explicitly in
  the compose files. Without them, a recreate empties both while the database
  rows survive and keep pointing at the missing bytes.
  **Upgrading an older install:** the previous container-layer copies are lost
  on any recreate anyway; copy them out first if they matter —
  `docker cp <app>:/home/career/.local/share/CareerAssistant ./data-backup`
  (and `.config/CareerAssistant`), then restore into the volumes:
  `docker run --rm -v "$PWD/data-backup:/from:ro" -v career-assistant_career_data:/to alpine sh -c 'cp -a /from/. /to/'`
  (same for `career-assistant_career_config`).
- **Operator feeder (ADR-0071, off by default)**: `bash scripts/install.sh
  --integrations-dir /srv/career/integrations` (or the one-time prompt on a
  first install) writes `docker/docker-compose.integrations.yml` and the two
  `CAREER_EXTENSION_*` values, so a bundle zip or a mounted folder can be
  imported without hosting a git repo. `--no-integrations` turns it off and
  removes only the installer-managed mount. Installs stay consent-gated,
  digest-pinned and disabled until enabled.
- Optional scheduled database backups (pg_dump to `./backups`; the
  uploads volume is covered by the manual tar step in the restore
  drill — see docs/dev/deployment.md):
  `--profile backup`.
- Deploy pre-built images instead of building:
  `CAREER_IMAGE=ghcr.io/<owner>/<repo>:<tag> docker compose ... up -d`
  (images are published by the release workflow on tags).

## Self-hosting from a release bundle (source-free)

Every GitHub release attaches a **source-free compose bundle**:
`career-compose-vX.Y.Z.tar.gz` + `manifest.json` + `SHA256SUMS`. The bundle
carries `docker/` (compose files, nginx configs, env example, entrypoint,
backup sidecar) + `scripts/{install,update,backup,restore,lib-docker}.sh` +
`installer.json` (the product config the self-host installer reads). No
source tree, no `.env`, no secrets; the app image is pinned by digest in
`manifest.json` and written to `CAREER_IMAGE` at install time.

One-line install (the bootstrap resolves the release, verifies the bundle
SHA-256, extracts and hands off to `scripts/install.sh`):

```bash
curl -fsSL https://neuronection.com/install/career.sh | bash
```

The cautious form — download it, read it, then run it:

```bash
curl -fsSL https://neuronection.com/install/career.sh -o career-bootstrap.sh
less career-bootstrap.sh
bash career-bootstrap.sh --dir ~/career-assistant
```

Bootstrap flags: `--dir DIR` (default `~/career-assistant`), `--ref vX.Y.Z`
(exact release instead of latest), `--dry-run` (resolve + verify + print the
hand-off, write nothing), `--offline career-compose-vX.Y.Z.tar.gz` (install
from an already-downloaded bundle, no GitHub download), `-- --http-port 8092`
(forward flags to the installer). The one-liner URL 302-redirects to the
GitHub release asset — the version-free `career-bootstrap.sh` alias of
`career-bootstrap-vX.Y.Z.sh` — so the script never comes from the website
itself. Until that route is published, run the same asset straight from the
release page.

Manual (no bootstrap — two commands, fully auditable):

```bash
# from the release assets: career-compose-vX.Y.Z.tar.gz + manifest.json + SHA256SUMS
sha256sum -c SHA256SUMS                                   # verify BEFORE extracting
mkdir -p ~/career-assistant
tar -xzf career-compose-vX.Y.Z.tar.gz -C ~/career-assistant
cp manifest.json ~/career-assistant/                       # the installer pins the image digest from it
cd ~/career-assistant
bash scripts/install.sh                                   # .env + pin + ports + up + health-wait
```

`scripts/install.sh` implements the family installer contract: refuses
root, never overwrites an existing `docker/.env`,
generates missing secrets (`umask 077`, values never printed), pins
`CAREER_IMAGE` from `manifest.json` (priority: `--image` > `--image-tag` >
`$CAREER_IMAGE` > manifest > existing `.env`), sets `HTTP_PORT`, pre-flights
every published port from `docker compose config` (naming the `.env` knob),
pulls, `up -d`, waits for `/health`, prints the URL + first-admin note +
backup/update/rollback hints. Idempotent — a re-run keeps `.env`, refreshes
images and re-runs `up -d`.

| Flag | Meaning |
|---|---|
| `--http-port PORT` | publish nginx on PORT (persisted as `HTTP_PORT` in `docker/.env`) |
| `--image-tag TAG` | pin images to a published release tag (`X.Y.Z` or `vX.Y.Z`) |
| `--image [KEY=]REF` | pin an explicit image ref (`--image app=ghcr.io/…@sha256:…`) — the KEY=REF form is what the bootstrap forwards; a bare REF overrides the primary image |
| `--env-only` | write `docker/.env` only, start nothing |
| `--no-pull` | reuse local images (offline hosts) |
| `--no-wait` | skip the `/health` wait |
| `--auto-ports` | move busy ports to free ones in `docker/.env` |
| `--no-ports` | skip the port pre-flight |
| `--reset [--yes]` | delete the stack's data volumes (listed first), then reinstall |
| `--allow-root` | CI/disposable containers only (refused by default) |
| `-h`, `--help` | the readable help block |

Exit codes: `0` ok · `1` usage/prerequisite · `2` image verify/pull ·
`3` compose start or health-wait · `4` port conflict.

**Updates** — download the new release's bundle, extract it over the same
directory (`docker/.env` is not in the bundle, so your secrets survive),
copy the new `manifest.json` in, then:

```bash
bash scripts/update.sh     # bump the pin from the new manifest, pull, up -d, wait
```

The previous `CAREER_IMAGE` pin is kept (a `# previous CAREER_IMAGE` comment
in `docker/.env` + the printed rollback command). No destructive data
operations: take a backup first (`scripts/backup.sh`), and roll back with the
previous pin + the pre-upgrade dump if `/health` fails — pre-1.0 schema
migrations have no downgrade path. The source-checkout equivalent remains
`scripts/update-docker.sh` (git pull + rebuild).

**Port plan.** The standalone stack publishes one host port (`HTTP_PORT`,
default 80). Running more than one Neuronection stack on the same host?
Give each a distinct port with `--http-port` (the family convention:
`8090` health · `8091` study · `8092` career) and keep the bundled nginx
HTTP-only behind your own TLS/VPN hop (`CAREER_PUBLIC_URL`/`CAREER_TLS`
control the cookie `Secure` derivation).

## Renaming `career_*` / `neuro_career_*` → `neuronection_*` (2026-09-30)

The family datastore prefix was amended (revision
history): databases `neuronection_career` (+ `neuronection_career_test` /
`neuronection_career_demo`) with bootstrap role `neuronection_career_owner`.
Career's legacy `POSTGRES_DB=career` default and the demo's
`neuro_career_demo` fold into that same pattern.

**Existing installations migrate automatically** (guarded, one-time, and a
complete no-op on fresh installs and on re-runs):

- `scripts/run-docker.sh` and `scripts/update-docker.sh` run
  `migrate_legacy_db_names()` (`scripts/lib-docker.sh`) **before** the stack
  boots: postgres is started first (an existing volume ignores
  `POSTGRES_DB` after first boot), the function probe-connects as the
  legacy bootstrap role (`career` → `neuro_career` → `admin`), then renames
  the database and the role.
- **Guarded:** a legacy name is renamed only when the new name is absent —
  if **both** exist, the run aborts with instructions (dump the old one,
  restore it into the new one, drop the old) instead of guessing. The same
  guard applies per role.
- PostgreSQL refuses to rename the session's own user, so the owner role is
  renamed through a throwaway `ca_db_migrator LOGIN SUPERUSER` (created →
  renamed from that session → dropped as the renamed owner; `DROP ROLE IF
  EXISTS` cleans up at both ends — you'll see it in the log).
- **Dev databases** are disposable: `./scripts/reset-test-db.sh`
  recreates `neuronection_career_test`, and
  `docker compose -f docker/docker-compose.dev-db.yml down -v` wipes the
  dev volume (the init scripts then recreate the new names). To rename an
  existing dev volume **in place** instead, run the same function against
  the dev stack:

  ```bash
  bash -c 'source scripts/lib-docker.sh; check_docker; \
    migrate_legacy_db_names postgres --env-file .env -f docker/docker-compose.dev-db.yml'
  ```
- **The demo database** is renamed manually (recipe below) or simply
  re-seeded: `docker compose -f docker/docker-compose.demo.yml --profile
  reset down -v`, then `up` again — demo data is synthetic.

Manual equivalent (standalone/prod flavor):

```bash
docker compose --env-file docker/.env -f docker/docker-compose.standalone.yml up -d db
C="docker compose --env-file docker/.env -f docker/docker-compose.standalone.yml exec -T db psql -d postgres -v ON_ERROR_STOP=1"
$C -U career -c 'ALTER DATABASE "career" RENAME TO "neuronection_career";'
$C -U career -c 'DROP ROLE IF EXISTS ca_db_migrator;'
$C -U career -c 'CREATE ROLE ca_db_migrator LOGIN SUPERUSER;'
$C -U ca_db_migrator -c 'ALTER ROLE career RENAME TO neuronection_career_owner;'
$C -U neuronection_career_owner -c 'DROP ROLE ca_db_migrator;'
```

Demo flavor (`neuro_career_demo` → `neuronection_career_demo`), with
`POSTGRES_PASSWORD` set (docker/.env or the shell):

```bash
docker compose -f docker/docker-compose.demo.yml up -d db
D="docker compose -f docker/docker-compose.demo.yml exec -T db psql -d postgres -v ON_ERROR_STOP=1"
$D -U neuro_career -c 'ALTER DATABASE "neuro_career_demo" RENAME TO "neuronection_career_demo";'
$D -U neuro_career -c 'DROP ROLE IF EXISTS ca_db_migrator;'
$D -U neuro_career -c 'CREATE ROLE ca_db_migrator LOGIN SUPERUSER;'
$D -U ca_db_migrator -c 'ALTER ROLE neuro_career RENAME TO neuronection_career_owner;'
$D -U neuronection_career_owner -c 'DROP ROLE ca_db_migrator;'
```

Backups taken before the rename restore unchanged (`pg_restore
--clean --if-exists` against the new name); the dump records no database
name.

## TLS

The default `nginx.conf` is HTTP-only — use it only behind a VPN or on
loopback. For internet-facing deployments:

1. Mount `nginx-TLS.conf` over `nginx.conf` (uncomment the commented volumes
   in the compose file, including `443:443`).
2. Provide certs at `docker/certs/fullchain.pem` + `privkey.pem`
   (certbot webroot renewals answer on port 80 via
   `/.well-known/acme-challenge/`).
3. Set `SERVER_NAME` in the conf to your domain.

## Docker CLI cheat sheet

```bash
docker compose -f docker/docker-compose.standalone.yml exec app bash     # app shell
docker compose -f docker/docker-compose.standalone.yml logs -f app       # follow logs
# Schema check + migrations (run the preflight first when doing this by hand:
# a pre-v0.17 volume is refused with guidance instead of migrated)
docker compose -f docker/docker-compose.standalone.yml run --rm app python -m careerassistant preflight
docker compose -f docker/docker-compose.standalone.yml run --rm app alembic upgrade head
```
