from __future__ import annotations

import os
from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

os.environ.setdefault("TRUSTED_LOCAL_WEB", "true")
os.environ.setdefault("API_TOKEN_PEPPER", "test-pepper-at-least-16-bytes")
# Force AI enrichment OFF by default so the suite is deterministic regardless of
# the container's real AI_BASE_URL/AI_API_KEY. Tests that need AI opt in via
# monkeypatch.setenv + get_settings.cache_clear().
os.environ["AI_BASE_URL"] = ""
os.environ["AI_API_KEY"] = ""
os.environ.pop("AI_API_KEY_FILE", None)
# Force cloud TTS OFF by default so tests never hit the real provider/key.
os.environ["TTS_BASE_URL"] = ""
os.environ["TTS_API_KEY"] = ""
os.environ.pop("TTS_API_KEY_FILE", None)
# Same for 豆包/VOLC — the import worker auto-enqueues audio for created words
# when a provider is configured, so tests must default to "no TTS". Tests that
# need it opt in via _audio_dir / monkeypatch.setenv + get_settings.cache_clear().
os.environ["VOLC_TTS_BASE_URL"] = ""
os.environ["VOLC_TTS_API_KEY"] = ""
os.environ.pop("VOLC_TTS_API_KEY_FILE", None)

from app.core.database import Base, build_engine, get_db
from app.main import app


@pytest.fixture
def db_session(tmp_path) -> Generator[Session, None, None]:
    engine = build_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    with factory() as session:
        yield session
    engine.dispose()


@pytest.fixture
def client(db_session: Session) -> Generator[TestClient, None, None]:
    def override_db():
        yield db_session

    app.dependency_overrides[get_db] = override_db

    # Point the background import worker at this test's engine so HTTP import
    # tests can observe the worker's writes. The module singleton otherwise uses
    # the production SessionLocal, which is a different database than db_session.
    from app.services import import_worker

    factory = sessionmaker(
        bind=db_session.get_bind(), autoflush=False, expire_on_commit=False
    )
    orig_factory = import_worker._worker._session_factory
    import_worker._worker._session_factory = factory
    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        try:
            import_worker._worker.wait_drained(timeout=10)
        except Exception:
            pass
        import_worker._worker._session_factory = orig_factory
        app.dependency_overrides.clear()


def drain_import_worker(timeout: float = 15.0) -> None:
    """Block until the background import worker finishes the current job.

    HTTP import tests call this after POST /import (which only enqueues) and
    before asserting on GET /import/progress or the word list.
    """
    from app.services.import_worker import _worker

    _worker.wait_drained(timeout=timeout)


@pytest.fixture
def db_factory(tmp_path) -> Generator[sessionmaker, None, None]:
    """A session factory on a fresh test engine.

    For worker-thread tests (import / audio workers) that open sessions inside a
    background thread — they cannot reuse the request-scoped ``db_session``.
    """
    engine = build_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    yield factory
    engine.dispose()


@pytest.fixture
def word_payload() -> dict[str, object]:
    return {
        "en_word": "Warm",
        "phonetic": "/wɔːm/",
        "cn_meaning": "温暖的",
        "example_sentence": "It's warm in spring.",
        "is_custom": False,
        "tags": ["basic"],
    }


def create_word(client: TestClient, payload: dict[str, object] | None = None) -> dict:
    response = client.post(
        "/api/v1/words",
        json=payload
        or {
            "en_word": "warm",
            "cn_meaning": "温暖的",
            "is_custom": False,
            "tags": [],
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["data"]


@pytest.fixture
def login_mode(monkeypatch):
    """Force the cookie-login path: disable loopback auto-admin and require login.

    The suite defaults to TRUSTED_LOCAL_WEB=true (loopback auto-admin), which
    bypasses the session-cookie branch entirely. Flipping it off (and login on)
    makes the cookie identity the only web path, so login/role tests are real.
    """
    from app.core.config import get_settings

    monkeypatch.setenv("TRUSTED_LOCAL_WEB", "false")
    monkeypatch.setenv("WEB_LOGIN_REQUIRED", "true")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def seed_credential(db_session: Session, username: str, password: str, role: str = "admin"):
    from app.core.auth import hash_password
    from app.models import WebCredential
    from app.models.entities import utc_now_text

    cred = WebCredential(
        username=username,
        password_hash=hash_password(password),
        role=role,
        created_at=utc_now_text(),
        updated_at=utc_now_text(),
    )
    db_session.add(cred)
    db_session.commit()
    db_session.refresh(cred)
    return cred
