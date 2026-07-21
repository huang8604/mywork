# Backend

Python 3.12 / FastAPI / SQLAlchemy 2 / SQLite backend shared by the phase three SPA.

Local setup:

    python3.12 -m venv .venv
    .venv/bin/pip install -e '.[test]'
    .venv/bin/alembic upgrade head
    .venv/bin/pytest
    .venv/bin/python scripts/export_openapi.py
    .venv/bin/uvicorn app.main:app --reload

Production must set DATABASE_URL, PUBLIC_BASE_URL, TRUSTED_HOSTS,
TRUSTED_PROXY_CIDRS and API_TOKEN_PEPPER_FILE. TRUSTED_LOCAL_WEB defaults to
false; enable it only for loopback-only local development. `FRONTEND_DIST` may
override the Vue production build directory; it defaults to `frontend/dist` at
the repository root. Existing API and health routes are never handled by the
SPA deep-link fallback.

The production container is built by the repo-root `Dockerfile` (multi-stage,
non-root UID 10001). Python dependencies are pinned with hashes in
`requirements.lock` (regenerate with
`pip-compile --generate-hashes --extra pdf -o requirements.lock pyproject.toml`,
Python 3.12) and installed with `pip install --require-hashes`. The `[pdf]`
extra (markdown + weasyprint) is included so the `/recitation` PDF endpoint
works; the image also installs the matching system libs + CJK fonts via apt.

English-only create/import uses `DICTIONARY_INDEX_PATH`, which defaults to
`dictionary-index.json` at the repository root. The file is intentionally not
tracked until its source and redistribution license are documented. Set
`LOG_LEVEL=DEBUG` during diagnosis to include dictionary misses, import counts,
route templates, latency, actor type and request IDs; tokens and request bodies
are never logged.
