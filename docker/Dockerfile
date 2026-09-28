# syntax=docker/dockerfile:1
# Multi-stage build: frontend bundle → single uvicorn image serving API + SPA.
#
# Build via compose (docker-compose.standalone.yml / .prod.yml /
# .demo.yml — each supplies the `auth-kit` named context) or:
#   docker build --build-context auth-kit=../auth-kit -f docker/Dockerfile .
# The `auth-kit` context supplies the family auth-kit (ADR-0013), which
# the dev venv pins as an editable path dependency (../auth-kit).

FROM node:20-alpine AS frontend-build
WORKDIR /build
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    SPA_DIST=/app/frontend/dist \
    APP_ENV=production \
    API_HOST=0.0.0.0

WORKDIR /app
COPY backend/requirements.txt ./
RUN pip install -r requirements.txt
# Family auth-kit (ADR-0013 / identity-auth §5) — named build context
# `auth-kit`, copied to /auth-kit and installed on top of the pinned
# requirements (its dependencies are already there).
COPY --from=auth-kit pyproject.toml README.md /auth-kit/
COPY --from=auth-kit src /auth-kit/src
RUN pip install --no-deps /auth-kit

COPY backend/app ./app
COPY backend/alembic ./alembic
COPY backend/alembic.ini ./
COPY --from=frontend-build /build/dist ./frontend/dist

COPY docker/entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh \
    && useradd --create-home --shell /usr/sbin/nologin career \
    && mkdir -p /app/uploads /data \
    && chown -R career:career /app /data
USER career

EXPOSE 8100
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD python -c "import os,urllib.request; urllib.request.urlopen(f'http://127.0.0.1:{os.getenv(\"API_PORT\",\"8100\")}/health', timeout=4)"

ENTRYPOINT ["entrypoint.sh"]
