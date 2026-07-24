#!/bin/sh
# Production container entrypoint.
#
# Runs versioned Alembic migrations against the mounted SQLite volume BEFORE
# starting uvicorn, so /healthz/ready (which asserts alembic_version == "0004")
# can pass on a fresh database. Failures here surface as a non-ready container
# rather than a silently-unmigrated one (phase-5 design §4.2).
#
# CWD is /app (the image WORKDIR); alembic.ini's `script_location = migrations`
# resolves relative to it. Runs as the non-root app user (UID/GID 10001), which
# owns /app/data (the only writable path).
set -eu

alembic upgrade head
# Provision the initial web admin from WEB_ADMIN_PASSWORD(_FILE) if none exists.
python -m app.bootstrap

exec "$@"
