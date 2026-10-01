# syntax=docker/dockerfile:1
# Multi-stage build: frontend bundle → single uvicorn image serving API + SPA.
#
# Build via compose (docker-compose.standalone.yml / .prod.yml /
# .demo.yml) or:  docker build -f docker/Dockerfile .
# The family auth-kit installs from its public git-SHA pin (uv clones it
# with transient `git`; the credentials dance and the named `auth-kit`
# build context are gone — the repo is public, study's image is proof).

FROM node:20-alpine AS frontend-build
WORKDIR /build
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_LINK_MODE=copy \
    PATH="/app/.venv/bin:$PATH" \
    SPA_DIST=/app/frontend/dist \
    CAREER_APP_ENV=production \
    CAREER_API_HOST=0.0.0.0

WORKDIR /app
COPY --from=ghcr.io/astral-sh/uv:0.9 /uv /usr/local/bin/uv

# Dependency layer first (cache-friendly): workspace manifests + lockfile.
# The auth-kit git-SHA pin clones from GitHub during sync; git is
# transient and purged before the layer commits (study's recipe).
COPY pyproject.toml uv.lock ./
COPY backend/pyproject.toml backend/pyproject.toml
COPY backend/app backend/app
COPY backend/careerassistant backend/careerassistant
RUN --mount=type=cache,target=/root/.cache/uv \
    apt-get update \
    && apt-get install -y --no-install-recommends git \
    && uv sync --frozen --no-dev \
    && apt-get purge -y git \
    && apt-get autoremove -y \
    && rm -rf /var/lib/apt/lists/*

# Code + runtime layers
COPY backend/alembic backend/alembic
COPY backend/alembic.ini backend/alembic.ini
COPY --from=frontend-build /build/dist ./frontend/dist

COPY docker/entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh \
    && useradd --create-home --shell /usr/sbin/nologin career \
    && mkdir -p /app/uploads /data \
    && chown -R career:career /app /data
USER career

EXPOSE 8100
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD python -c "import os,urllib.request; urllib.request.urlopen(f'http://127.0.0.1:{os.getenv(\"CAREER_API_PORT\",\"8100\")}/health', timeout=4)"

ENTRYPOINT ["entrypoint.sh"]
