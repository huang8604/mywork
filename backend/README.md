# Backend

Python 3.12 / FastAPI / SQLAlchemy 2 / SQLite implementation of phase two.

Local setup:

    python3.12 -m venv .venv
    .venv/bin/pip install -e '.[test]'
    .venv/bin/alembic upgrade head
    .venv/bin/pytest
    .venv/bin/python scripts/export_openapi.py
    .venv/bin/uvicorn app.main:app --reload

Production must set DATABASE_URL, PUBLIC_BASE_URL, TRUSTED_HOSTS,
TRUSTED_PROXY_CIDRS and API_TOKEN_PEPPER_FILE. TRUSTED_LOCAL_WEB defaults to
false; enable it only for loopback-only local development.
