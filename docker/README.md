# Career Assistant - Docker Utilities & Cheat Sheet

This directory contains the Docker configuration files for Career Assistant.
It mirrors Health Assistant's docker layout (family standard).

For development on the host see the root `README.md` and `scripts/run-dev.sh`.

## File map

| File | Purpose |
|---|---|
| `docker-compose.dev-db.yml` | Dev infrastructure only: Postgres :5433 + Redis :6380 for host-based development (`scripts/run-dev.sh`). |
| `docker-compose.prod.yml` | Production services (app + Postgres). Proxy handled externally or via the standalone flavor. Supports `CAREER_IMAGE` to deploy pre-built GHCR images. |
| `docker-compose.standalone.yml` | Canonical self-hosted single-host stack: app + Postgres + nginx (TLS-ready). |
| `Dockerfile` | Multi-stage: frontend bundle → single uvicorn image serving API + SPA. |
| `entrypoint.sh` | Waits for the DB, runs migrations, starts uvicorn. |
| `nginx.conf` | HTTP-only reverse proxy (loopback / VPN). |
| `nginx-TLS.conf` | TLS-terminating variant (certbot webroot ACME + HSTS). |
| `init-test-db.sh` / `init-test-db` | Creates the `career_test` DB used by pytest. |

## Dev infrastructure (host-based development)

```bash
docker compose -f docker/docker-compose.dev-db.yml up -d   # Postgres :5433 + Redis :6380
./scripts/run-dev.sh                                       # backend :8100 + frontend :3100
```

## Self-hosting (standalone flavor)

```bash
cp docker/.env.production.example docker/.env    # then edit secrets
docker compose -f docker/docker-compose.standalone.yml up -d --build
```

- App + Postgres + nginx; the app image serves API and SPA same-origin.
- Optional scheduled backups (dump + uploads to `./backups`):
  `--profile backup`.
- Deploy pre-built images instead of building:
  `CAREER_IMAGE=ghcr.io/<owner>/<repo>:<tag> docker compose ... up -d`
  (images are published by the release workflow on tags).

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
docker compose -f docker/docker-compose.standalone.yml run --rm app alembic upgrade head
```
