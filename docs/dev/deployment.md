# Deployment Guide

Self-hosting Career Assistant. The recommended path is the production
compose stack — one container runs the API **and** the built web app, so a
fresh install is: clone → configure → `docker compose up`.

---

## Quick start (Docker Compose)

Prerequisites: Docker + Docker Compose v2, a machine with ports 8100 (or your
choice) reachable, or ports 80/443 for the optional proxy.

```bash
git clone https://github.com/neuronection/career-assistant.git
cd career-assistant

cp docker/.env.production.example docker/.env
# Edit docker/.env — set the three CAREER_*_KEY secrets and
# POSTGRES_PASSWORD (long random values; generate each key separately)

docker compose -f docker/docker-compose.prod.yml up -d --build
```

The app is on `http://<host>:8100`. Migrations run automatically on every
start. For a single-host stack with bundled nginx (TLS-ready) use
`docker/docker-compose.standalone.yml` instead — see *TLS with the bundled
nginx* below. First-time deploys can also use `./scripts/run-docker.sh`;
existing installs refresh via `./scripts/update-docker.sh`.

### First boot walkthrough

1. **Register the admin** — the web deployment runs the family
   `authenticated` instance mode (identity-auth §4): the first boot shows
   the login screen, register the first user (it automatically becomes
   the admin). The desktop app (`python -m careerassistant`) runs `open`
   instead — no login at all (Desktop Identity Mode, implicit local
   owner). Modes are set once on an empty database (`CAREER_AUTH_MODE`)
   and are DB-authoritative afterwards.
2. **Load the starter catalog** (optional, recommended):
   `./scripts/seed.sh` against the compose database (see *Bare metal access*
   below), or leave it empty and generate everything with AI.
3. **Configure AI** — Settings → AI Configuration. A fresh production install
   starts unconfigured: AI endpoints answer `503` until an admin adds a
   provider (OpenAI, OpenRouter, or a local Ollama/LM Studio via an
   OpenAI-compatible base URL). There are deliberately no `AI_*` env vars.
4. Onboard your profile and start exploring.

### Configuration reference (docker/.env)

| Variable | Required | Default | Notes |
|---|---|---|---|
| `CAREER_SESSION_KEY` / `CAREER_REFRESH_KEY` / `CAREER_DATA_KEY` | yes | — | The per-purpose key family (identity-auth §8): session-JWT signing / refresh-JWT signing / Fernet for secrets at rest. Three **independent** secrets, all three or none (partial pins fail closed) — generate each with `python3 -c 'import secrets; print(secrets.token_urlsafe(32))'`. Never derived from each other. |
| `CAREER_TRUSTED_PROXY_COUNT` | no | `1` (compose) | Rightmost `X-Forwarded-For` hops trusted for per-IP limits (§7/§16). The compose stacks are proxy-fronted by design; keep `1` behind one proxy, `0` for direct exposure. |
| `CAREER_AUTH_MODE` | no | `authenticated` | Init-only instance mode (`open` is desktop-only and refused on server). Post-init flips are ignored. |
| `CAREER_REGISTRATION_ENABLED` | no | `true` | Disable to close the public registration route. |
| `CAREER_COOKIE_SECURE` | no | `false` | Set `true` behind TLS so session cookies get `Secure`. |
| `CAREER_AUTH_ACCESS_TTL_MINUTES` / `CAREER_AUTH_REFRESH_TTL_DAYS` / `CAREER_AUTH_REFRESH_ABSOLUTE_DAYS` | no | `60` / `7` / `30` | Session lifetimes (identity-auth §8). |
| `CAREER_AUTH_LOCKOUT_THRESHOLD` / `CAREER_AUTH_LOCKOUT_MINUTES` | no | `5` / `15` | Login brute-force lockout (§7). |
| `CAREER_RATELIMIT_AUTH` / `_AUTH_EMAIL` / `_AI` / `_MCP` / `_DEFAULT` | no | `10` / `30` / `30` / `120` / `240` | Per-bucket rate ceilings, requests/minute (`0` disables a bucket). |
| `POSTGRES_PASSWORD` | yes | — | Password for the bundled Postgres. |
| `POSTGRES_DB` / `POSTGRES_USER` | no | `career` | Database name/user. |
| `API_PORT` | no | `8100` | Host port the app publishes on. |
| `MAX_UPLOAD_MB` | no | `25` | University PDF upload cap. |
| `CORS_ORIGINS` | no | *(empty)* | Only needed if you serve the SPA from a different origin than the API. |
| `CAREER_IMAGE` | no | `career-assistant:local` | Deploy a pre-built registry image (e.g. `ghcr.io/neuronection/career-assistant:vX.Y.Z`) instead of building. |
| `HTTP_PORT` | standalone | `80` | Host port the bundled nginx publishes on (standalone flavor). |

### TLS with the bundled nginx (standalone flavor)

Point a DNS A/AAAA record at the host, then use the standalone stack:

```bash
docker compose -f docker/docker-compose.standalone.yml up -d --build
```

By default it serves HTTP on port 80 — fine for VPN/loopback only. For
internet-facing TLS: set `SERVER_NAME` in `docker/nginx-TLS.conf`, provide
certs at `docker/certs/{fullchain,privkey}.pem` (certbot webroot renewals
answer on port 80), uncomment the TLS volumes and the `443:443` mapping in
the compose file, and swap the mounted conf to `nginx-TLS.conf`. nginx
streams SSE without buffering and enforces a 64 MB body cap (keep it ≥
`MAX_UPLOAD_MB`).

## Upgrades

```bash
cd career-assistant
./scripts/update-docker.sh     # git pull + rebuild + restart + health-wait
```

Or manually: `git pull`, back up first (see Backups), then
`docker compose -f docker/docker-compose.prod.yml up -d --build`.

The container runs `alembic upgrade head` on start, so schema migrations
apply automatically. Pre-1.0 there is **no downgrade path** — pin a version
tag if you need reproducibility.

When upgrading from a pre-P3d release, set the three `CAREER_*_KEY`
secrets in `docker/.env` **before** the first start (see the
configuration reference) and re-enter your AI provider keys once in
Settings → AI Configuration — migration `0044` wipes stored provider
keys and re-encrypts-or-clears the remaining sealed values (GitHub token,
VAPID push keys, MCP bridge tokens) under `CAREER_DATA_KEY`.

## Backups

Two things hold state: the Postgres volume (`db_data`) and the uploads volume
(`uploads_data`).

```bash
# Database (logical dump)
docker compose -f docker/docker-compose.prod.yml exec db \
  pg_dump -U career -Fc career > backup-$(date +%F).dump

# Uploaded documents (PDFs)
docker run --rm -v career-assistant_uploads_data:/data -v "$PWD":/out alpine \
  tar czf /out/uploads-$(date +%F).tar.gz -C /data .

# Restore
docker compose -f docker/docker-compose.prod.yml exec -T db \
  pg_restore -U career -d career --clean < backup-YYYY-MM-DD.dump
```

Schedule both (cron) and keep copies off-machine. (A built-in backup/export
UI is planned.)

## Reverse proxy (bring your own)

Any proxy works as long as it does not buffer responses (future SSE
endpoints) and allows request bodies ≥ `MAX_UPLOAD_MB`.

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

Python 3.12+, Node 20+, and a reachable Postgres 16:

```bash
# Build the SPA
cd frontend && npm ci && npm run build && cd ..

# Backend
cd backend
python -m venv venv && ./venv/bin/pip install -r requirements.txt
export APP_ENV=production
export DATABASE_URL=postgresql+asyncpg://user:pass@127.0.0.1:5432/career
export CAREER_SESSION_KEY="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"
export CAREER_REFRESH_KEY="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"
export CAREER_DATA_KEY="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"
./venv/bin/alembic upgrade head
./venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8100
```

The app auto-detects `../frontend/dist` and serves it — no separate web
server needed. Run under systemd (`Restart=on-failure`,
`StateDirectory=career-assistant`) and front it with nginx/Caddy for TLS
(set `CAREER_TRUSTED_PROXY_COUNT=1` and `CAREER_COOKIE_SECURE=true` there).

Boot guards: production refuses to start with a weak, partial or missing
key family (`CAREER_SESSION_KEY` / `CAREER_REFRESH_KEY` /
`CAREER_DATA_KEY`) or `DEBUG=true` — this is intentional.

## Troubleshooting

- **`503` on AI features** — no provider configured; see First boot
  walkthrough step 3.
- **`413` on PDF upload** — raise `MAX_UPLOAD_MB` and your proxy body cap.
- **Container restart loop** — check logs for the boot guard message
  (`docker compose -f docker/docker-compose.prod.yml logs app`); usually a
  weak or missing `CAREER_*_KEY` secret.
- **Health check** — `GET /health` returns JSON liveness info; wire your
  monitor to it.
