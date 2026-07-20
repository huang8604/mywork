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
