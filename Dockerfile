# Single-container full-stack image for the word-memory assistant.
#   stage 1 — build the Vue SPA with Node
#   stage 2 — run FastAPI (serves API + the built SPA) on Python
#
# Phase-5 design: base images pinned to a version + digest; runtime is non-root
# (UID/GID 10001) with only /app/data writable; /healthz/* and /api/v1/* are
# never swallowed by the SPA fallback (route order is fixed in app/main.py).
#
# Build context is the repo root:
#   docker build -t ghcr.io/huang8604/vocab-app:local .

# --- stage 1: frontend -----------------------------------------------------------------
# node:22-alpine (Vite 7 / vue-tsc 3 require Node 20.19+ or 22.12+).
FROM node:22-alpine@sha256:16e22a550f3863206a3f701448c45f7912c6896a62de43add43bb9c86130c3e2 AS frontend-builder

WORKDIR /build/frontend
# Install deps from the committed lockfile first for layer caching.
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
# Produce dist/. Unit tests are gated in CI (frontend job), not during the
# image build, to keep the artifact step focused and fast.
RUN npm run build

# --- stage 2: backend + SPA host -------------------------------------------------------
# python:3.12-slim (Debian trixie-slim). Multi-arch index digest works on
# amd64 and arm64.
FROM python:3.12-slim@sha256:57cd7c3a7a273101a6485ba99423ee568157882804b1124b4dd04266317710de AS backend-runner

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    FRONTEND_DIST=/app/static \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Runtime system libraries for WeasyPrint (phase-4 /recitation PDF export) +
# Noto CJK fonts so the PDF renders Chinese glyphs. Without these the PDF
# endpoint 500s, even though the app imports fine (weasyprint is lazily imported).
# hadolint ignore=DL3008
# Acquire::Retries survives transient registry/proxy hiccups (e.g. 502s).
RUN apt-get update \
    && apt-get install -y --no-install-recommends -o Acquire::Retries=5 \
        fonts-noto-cjk \
        libpango-1.0-0 \
        libpangoft2-1.0-0 \
        libharfbuzz0b \
        libfontconfig1 \
        libcairo2 \
    && rm -rf /var/lib/apt/lists/*

# Non-root user. Fixed UID/GID 10001 must match the NAS host data directory.
RUN groupadd --gid 10001 app \
    && useradd --uid 10001 --gid app --no-create-home --shell /usr/sbin/nologin app

# Install locked Python dependencies before copying app code (layer cache).
COPY backend/requirements.lock ./
# `--require-hashes` enforces the pinned, hashed lockfile (see requirements.lock
# header). If the lockfile was generated without hashes, drop this flag.
RUN pip install --no-cache-dir --require-hashes -r requirements.lock

# Application code + Alembic + entrypoint.
COPY --chown=app:app backend/ ./
# Built SPA, served as static files / SPA fallback by app/main.py.
COPY --chown=app:app --from=frontend-builder /build/frontend/dist /app/static

RUN chmod +x /app/docker-entrypoint.sh \
    && mkdir -p /app/data \
    && chown -R app:app /app/data

USER 10001:10001
EXPOSE 8000

# Liveness only — readiness (/healthz/ready) checks the DB + migration, which is
# a richer signal than the container engine needs for restart decisions.
HEALTHCHECK --interval=30s --timeout=3s --start-period=20s --retries=3 \
  CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz/live', timeout=2)"]

# Run migrations against the mounted SQLite volume, then start uvicorn behind a
# trusted reverse proxy (--proxy-headers; FORWARDED_ALLOW_IPS set at runtime).
ENTRYPOINT ["/app/docker-entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
