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
# Edit docker/.env — set JWT_SECRET and POSTGRES_PASSWORD (long random values)

docker compose -f docker/docker-compose.prod.yml up -d --build
```

The app is on `http://<host>:8100`. Migrations run automatically on every
start.

### First boot walkthrough

1. **Register the first user** — it automatically becomes the instance admin.
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
| `JWT_SECRET` | yes | — | Long random string. **Never** reuse the dev default. |
| `POSTGRES_PASSWORD` | yes | — | Password for the bundled Postgres. |
| `POSTGRES_DB` / `POSTGRES_USER` | no | `career` | Database name/user. |
| `API_PORT` | no | `8100` | Host port the app publishes on. |
| `MAX_UPLOAD_MB` | no | `25` | University PDF upload cap. |
| `CORS_ORIGINS` | no | *(empty)* | Only needed if you serve the SPA from a different origin than the API. |
| `CA_DOMAIN` | with proxy | — | Public hostname for the Caddy TLS proxy. |

### TLS with the bundled Caddy (optional)

Point a DNS A/AAAA record at the host, set `CA_DOMAIN` in `docker/.env`, then:

```bash
docker compose -f docker/docker-compose.prod.yml --profile proxy up -d
```

Caddy terminates TLS (automatic Let's Encrypt), streams SSE without
buffering, and enforces a 64 MB body cap (keep it ≥ `MAX_UPLOAD_MB`).

## Upgrades

```bash
cd career-assistant
git pull
# back up first (see Backups)
docker compose -f docker/docker-compose.prod.yml up -d --build
```

The container runs `alembic upgrade head` on start, so schema migrations
apply automatically. Pre-1.0 there is **no downgrade path** — pin a version
tag if you need reproducibility.

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
UI is planned — see `dev/plans/14-data-portability.md`.)

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
export JWT_SECRET="$(python3 -c 'import secrets; print(secrets.token_urlsafe(48))')"
./venv/bin/alembic upgrade head
./venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8100
```

The app auto-detects `../frontend/dist` and serves it — no separate web
server needed. Run under systemd (`Restart=on-failure`,
`StateDirectory=career-assistant`) and front it with nginx/Caddy for TLS.

Boot guards: production refuses to start with a weak `JWT_SECRET` or
`DEBUG=true` — this is intentional.

## Troubleshooting

- **`503` on AI features** — no provider configured; see First boot
  walkthrough step 3.
- **`413` on PDF upload** — raise `MAX_UPLOAD_MB` and your proxy body cap.
- **Container restart loop** — check logs for the boot guard message
  (`docker compose -f docker/docker-compose.prod.yml logs app`); usually a
  weak `JWT_SECRET`.
- **Health check** — `GET /health` returns JSON liveness info; wire your
  monitor to it.
