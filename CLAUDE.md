# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project context

Single-user, NAS-deployed vocabulary practice system (单词记忆辅助系统). UI and design docs are in Chinese; code and identifiers are in English. The primary loop is **offline**: generate a printable word worksheet, review on paper, then come back to the web app to record three-state results (`known` / `unknown` / `skipped`). Online flashcard review is a secondary, occasional path. Both paths share the same data model and result-recording rules.

Development is staged into six phases with frozen decisions under `docs/design/`; implementation plans and execution records live under `docs/superpowers/`. Phases 1–6 are implemented. Each phase doc or enhancement spec defines the completion gates for its scope.

### Production image, CI, and NAS deploy (phase 5)

- **Image**: repo-root `Dockerfile` is multi-stage — `node:22-alpine` builds the Vue SPA (`npm ci` + `npm run build`), `python:3.12-slim` runs FastAPI serving API + the built SPA. Base images are pinned to a version+digest. Runtime is non-root UID/GID 10001 (only `/app/data` writable). `backend/docker-entrypoint.sh` runs `alembic upgrade head` before `uvicorn`, so `/healthz/ready` passes on a fresh DB. The runtime stage installs weasyprint system libs + `fonts-noto-cjk` so the phase-4 `/recitation` PDF endpoint works.
- **Locked deps**: `backend/requirements.lock` is a hashed, fully-pinned lockfile (includes the `[pdf]` extra); the Dockerfile installs it with `pip install --require-hashes`. Regenerate with `pip-compile --generate-hashes --extra pdf -o requirements.lock pyproject.toml` (Python 3.12).
- **CI**: `.github/workflows/ci.yml` runs gates on push-to-main and PR (backend `ruff check app tests` + `pytest`; frontend `typecheck` + vitest + build; OpenAPI-contract drift check; docker build + container smoke test of `/healthz/*` + SPA deep link + API-not-swallowed; Trivy HIGH/CRITICAL scan). Only push-to-main publishes `ghcr.io/huang8604/vocab-app:latest` + `sha-<short>` to GHCR. Third-party actions are pinned to commit SHAs.
- **NAS**: ignored local file `deploy/portainer-stack.yml` is the current NAS/Lucky deployment; tracked `deploy/portainer-stack.template.yml` is the reusable `REPLACE_ME` template; `deploy/README.md` is the runbook. Release is **manual**: operator backs up the DB, then Pulls the selected tag + Recreates in Portainer. No Watchtower/webhook/auto-pull. Rollback targets a `sha-<commit>` tag, not `latest`.

## Common commands

### Backend (`backend/`)

```bash
python3.12 -m venv .venv
.venv/bin/pip install -e '.[test]'
.venv/bin/alembic upgrade head          # apply migrations; creates data/vocab.db
.venv/bin/pytest                        # full suite (via fastapi.testclient + httpx)
.venv/bin/pytest tests/test_words_reviews.py::test_word_crud_soft_delete_restore_and_global_uniqueness  # single test
.venv/bin/python scripts/export_openapi.py   # regenerate contracts/openapi.yaml
.venv/bin/uvicorn app.main:app --reload      # dev server on :8000
```

Backend tests use FastAPI `TestClient` with `app.dependency_overrides[get_db]` injected to a per-test SQLite DB (`conftest.py`). `conftest.py` sets `TRUSTED_LOCAL_WEB=true` and a test `API_TOKEN_PEPPER` automatically — tests impersonate a loopback web admin.

API client/token lifecycle scripts (run with the venv against the production DB):
`scripts/create_api_client.py`, `rotate_api_token.py`, `revoke_api_client.py`, `set_api_client_scopes.py`, `list_api_clients.py`, `rebuild_stats.py`, `backup_sqlite.py`.

### Frontend (`frontend/`)

```bash
npm install
npm run dev          # Vite on :5173, proxies /api and /healthz → http://127.0.0.1:8000
npm run typecheck    # vue-tsc -b
npm test             # vitest unit (jsdom)
npm run build
npm run test:e2e     # Playwright across 320/375/768/1024/1440 viewports
```

Backend dev server needs `TRUSTED_LOCAL_WEB=true` for the browser to authenticate as loopback admin.

### LAN / Docker debugging (`dev-lan.sh`)

The host only has Python 3.8 (backend needs 3.10+), so LAN debugging runs the backend in a container rather than a venv. `dev-lan.sh` at the repo root automates it:

```bash
./dev-lan.sh             # backend container + Vite (default)
./dev-lan.sh backend     # container only
./dev-lan.sh frontend    # Vite only
```

It publishes the container on `127.0.0.1:8001` (host `:8000` is taken by the sibling `signtools` project), auto-detects the LAN IP, recreates the container if the IP changed, health-checks, and starts Vite with `VITE_API_TARGET=http://127.0.0.1:8001`. Open the printed `http://<lan-ip>:5173` from any device. The Vite dev proxy injects `X-Forwarded-User` (`vite.config.ts`, `VITE_PROXY_USER`) because Docker's port publishing makes the request appear to come from the docker bridge (`172.16/12`, a trusted-proxy CIDR) instead of loopback, so `TRUSTED_LOCAL_WEB` doesn't apply and the trusted-proxy auth branch requires that header. Data lives in `/tmp/myword-lan-data` (ephemeral). The container's uvicorn has no `--reload`; restart it after backend edits. To run pytest inside the container, override the LAN-prod env: `TRUSTED_HOSTS=localhost,127.0.0.1,testserver PUBLIC_BASE_URL=http://localhost:8000 CORS_ORIGINS=http://localhost:8000 pytest -q`.

## Architecture

### Backend layering (FastAPI + SQLAlchemy 2 + SQLite)

Strict four-layer separation; nothing bypasses it:

- `app/api/*.py` — route handlers. Thin: validate scope, call service, wrap result in `envelope()`, write audit, commit. **Routes never touch the DB directly except via services.** Each module has a `_commit(db)` helper that rolls back on failure.
- `app/services/*.py` — business logic and all DB mutations in one transaction. `words.py` (CRUD, soft-delete, list/export filters), `reviews.py` (three-state write + correction + stats rebuild), `strategy.py` (worksheet generation), `dictionary.py` (enrichment), `idempotency.py`, `domain.py` (normalization, time, stats math, canonical JSON), `serializers.py` (ORM → dict).
- `app/models/entities.py` — all SQLAlchemy models, constraints, and indexes in one file.
- `app/schemas/contracts.py` — Pydantic v2 **strict** models (`StrictModel` with `extra="forbid"`). The single source for request shapes.
- `app/core/` — cross-cutting: `auth.py`, `config.py` (`Settings` from env, `lru_cache`d), `database.py`, `errors.py` (`AppError`), `responses.py` (`envelope`), `audit.py`.

### Response & error contract

Every `/api/v1` JSON success is wrapped by `envelope()` in `core/responses.py`:
```json
{"code": "OK", "message": "success", "data": ..., "meta": {...}, "request_id": "..."}
```
Errors use `{"code", "message", "details": [...], "request_id"}`. Raise `AppError(status, code, message, details, headers)` **anywhere** in the call stack — handlers in `main.py` convert it (plus `RequestValidationError`, `IntegrityError`, SQLite `OperationalError`) to the error envelope. Always raise `AppError`/`not_found()`/`validation()` rather than `HTTPException`. The SQLite-busy branch returns `503 SERVICE_BUSY` with `Retry-After`.

### Authentication & authorization (bearer + three web paths)

`get_actor` (in `core/auth.py`, applied via `require_scopes(...)`) resolves identity in this order:

1. **External Skill / API client** — Argon2-hashed Bearer token (`wm_...`), prefix-indexed, rate-limited per peer+identity, with explicitly granted scopes from `ApiClientScope`.
2. **Web login (session cookie)** — a `wm_session` cookie signed by Starlette `SessionMiddleware` (secret = `SESSION_SECRET(_FILE)`, defaulting to the token pepper). The cookie holds only `{sub: username}`; on each request `_session_actor` looks up `WebCredential` for the current role + disabled state, so role/disable changes take effect immediately. Scopes come from `ROLE_SCOPES`: `admin` → all scopes, `student` → `{practice:generate, practice:read, reviews:write}` (the online-review flow only). This is the path behind the `/login` page.
3. **Local dev** — `TRUSTED_LOCAL_WEB=true` + loopback peer → full-admin `local-admin`.
4. **Trusted reverse proxy** — `X-Forwarded-User` accepted only from `TRUSTED_PROXY_CIDRS`, granted all scopes. **Skipped entirely when `WEB_LOGIN_REQUIRED=true`** — that flag makes the cookie login the only web path (use it to expose the app publicly behind HTTPS without relying on the proxy to vouch for identity).

`Actor` carries `actor_type`, `actor_id`, `scopes`, `role` (web only), and optional `api_client_id`/`skill_name`/`skill_version`. CSRF on cookie-authenticated writes is handled by the existing Origin check in `main.py` (`Origin == PUBLIC_BASE_URL` for POST/PUT/PATCH/DELETE) — no separate CSRF token. The route→scopes mapping is `REQUIRED_SCOPES` in `main.py` (injected into OpenAPI as `x-required-scopes`); `/api/v1/auth/*`, `/api/v1/users/*`, `/api/v1/api-clients/*`, and `/api/v1/system/backup` are intentionally NOT scope-gated — they are admin-only via the `require_web_admin` dependency (`Actor.role == "admin"`), keeping `ALL_SCOPES` (the API-client scope universe) unchanged. The plaintext API token is returned **only** on create/rotate responses (never on list/get). **When adding or changing a route, update `REQUIRED_SCOPES` there** (and re-export the OpenAPI contract).

The initial admin is bootstrapped from `WEB_ADMIN_USERNAME`/`WEB_ADMIN_PASSWORD(_FILE)` by `app/bootstrap.py` (run from `docker-entrypoint.sh`); admin then creates students via the 用户管理 page or `scripts/set_web_password.py --role student`. Self-delete / last-admin deletion is refused (lockout guard).

### Idempotency & optimistic locking

Three overlapping safety mechanisms — know which applies where:

- **`Idempotency-Key` header** → `claim()`/`complete()` in `services/idempotency.py`. Required for API clients on most writes; required for *everyone* on worksheet generation (`/daily-table/generate`) and round creation. Replaying the same key+payload returns the cached response with `Idempotency-Replayed: true`; same key+different payload → `409 IDEMPOTENCY_KEY_REUSE`.
- **`client_event_id`** (per-review, not a header) → dedupes individual review writes via a unique constraint + `ON CONFLICT DO NOTHING`. Reuse with a *different* status → `409 IDEMPOTENCY_KEY_REUSE`.
- **`version` / `expected_version`** → optimistic locking on `Word`, `PracticeSession`, `PracticeReviewRound`, `ReviewLog`. Mismatch → `409 VERSION_CONFLICT`. Word delete uses `If-Match` header; everything else uses a body field.

### Word creation & dictionary enrichment

Creating/importing a word runs through `enrich_word()` (`services/dictionary.py`), which fills `phonetic` / `cn_meaning` / `example_sentence` from `dictionary-index.json` at the repo root (path overridable via `DICTIONARY_INDEX_PATH`). `cn_meaning` is then shortened to **≤16 chars** via `shorten_translations()` (multi-boundary cut on `。；，`; if still >16 and `ai_enabled`, AI re-translates; otherwise it is hard-capped to ≤16 characters including `…`). **`cn_meaning` is required after enrichment** — an English-only word with no dictionary entry raises `422 DICTIONARY_ENTRY_NOT_FOUND` unless a meaning is supplied. Only the enrich path is affected; existing words are not re-shortened. The index file is large and **intentionally git-ignored** (license not yet documented); don't commit it. If the file is missing, enrichment resolves to "not found".

### Cloud TTS audio

Words can carry server-generated MP3 pronunciation metadata (`audio_path`, `audio_format`, `audio_voice`, `audio_generated_at`, `audio_bytes`). The backend calls the configured TTS provider from `services/tts.py`; Vue never receives the provider key. Generated files are written under `TTS_AUDIO_DIR` when set, otherwise beside the SQLite DB under `audio/` (production: `/app/data/audio`), using a temp file + fsync + atomic `os.replace`. Admin word routes generate/read audio under `words:*`; students do **not** receive `words:read`, so `/api/v1/practice-sessions/{session_id}/items/{item_id}/audio` exposes only the session item's MP3 under `practice:read`. Online dictation tries that MP3 first and falls back to browser `speechSynthesis` when the file is missing or playback fails. Tests must mock `app.services.tts.synthesize_word_mp3` and keep `TTS_BASE_URL`/`TTS_API_KEY` empty by default.

### Worksheet generation (strategy engine)

`generate_session()` in `services/strategy.py` builds four priority pools consumed in order `error → new → due → custom` (`PRIORITY`), assigns each word all its source labels, and selects up to `MAX_PRACTICE_WORDS`. When a pool can't fill its quota the shortfall cascades to the next pool, so the total still reaches `sum(limits)` whenever enough words exist (Plan-A backfill). Output is **deterministic given the seed** (`seed` persisted on the session; `strategy_hash` over canonicalized params). Each `PracticeSessionItem` snapshots the word's text at generation time so printed worksheets stay stable as the word library changes. Supports either category-quota selection or an explicit `word_ids` list (preserves user order).

### Exports layout (worksheet + md + pdf)

The printed worksheet and the `/recitation` md/pdf all render the word + `/phonetic/` (phonetic wrapped in `/ /`) on **one line** with no wrap; the blanked side renders **empty** (no underlines); the example is shown **in full** (the 例句填空 / cloze mode was removed). This keeps each row compact and consistent across print, markdown, and PDF.

### Stats rebuild

`WordStats` is always **rebuilt from the ordered `ReviewLog` stream**, never incrementally mutated — `rebuild_word_stats()` calls `calculate_stats()` (`services/domain.py`). Spacing interval is `(1,3,7,14,30)` days indexed by `consecutive_known`; `due_at` = last effective review + interval. `skipped` does not count toward accuracy or interval. Correcting a review mutates the log row and rebuilds stats in the same transaction.

### SQLite configuration

Every SQLite connection sets `PRAGMA foreign_keys=ON`, `journal_mode=WAL`, `busy_timeout=5000` (`core/database.py`). Imports use `BEGIN IMMEDIATE` for atomicity. All timestamps are stored as UTC ISO-8601 strings ending in `Z` (`utc_text()`); the app timezone (`APP_TIMEZONE`) only affects display/“today” computation.

### SPA hosting

In production the backend serves the built SPA from `FRONTEND_DIST` (default `frontend/dist`). `spa_fallback()` serves static assets and falls back to `index.html` for deep links, but **never** intercepts `api/`, `healthz/`, or `.well-known/` paths.

### Admin tooling (`/system` page)

The `/system` route (`meta.roles: ['admin']`) is the admin console: API-client/token management (create, rotate, revoke, adjust scopes — the plaintext token is shown only on create/rotate) and one-click SQLite full-backup download (`GET /api/v1/system/backup` streams a `.db` snapshot). It replaces the CLI lifecycle scripts for day-to-day admin.

## Frontend conventions

- Axios `apiClient` (`src/api/client.ts`) is fixed at `/api/v1`; callers unwrap the envelope with `unwrap()` to get `.data`, and treat export endpoints as `Blob`. `ApiError` normalizes all failures (status → Chinese message map); `.isConflict` / `.isCanceled` helpers drive UI.
- **`src/types/domain.ts` is the source of truth for response types**, not OpenAPI — the backend's success schemas are not fully described, and types are validated by API unit tests + e2e mocks instead.
- Routing in `src/router/index.ts`; each nav route carries `meta` used for labels and document title. Responsive breakpoints in `src/styles/breakpoints.css`; print rules in `src/styles/print.css`.
- `newEventId()` generates the `client_event_id` for each review submission; `formatPhonetic` (`@/utils/formatPhonetic`) wraps a raw phonetic string in `/ /` for display (shared across worksheet, review, and recitation views).
- **Auth**: `useAuthStore` (`stores/auth.ts`) holds the logged-in identity (`username`/`role`); the router `beforeEach` awaits `fetchMe()` once, then enforces each route's `meta.roles` (`admin` sees everything, `student` only `/review`; `/system` is `['admin']`). `apiClient` uses `withCredentials` and, on a non-`/auth/*` 401, clears the store and redirects to `/login`. Login is a server-set session cookie — no token lives in JS.
- **Audio**: word-library controls call `src/api/words.ts` to generate MP3s and play `/api/v1/words/{id}/audio`; `OnlineDictation.vue` passes practice-item audio URLs to `useDictationPlayer`, which tries server MP3 first and falls back to `speechSynthesis` without exposing any TTS key in JS.

## External Skills

The repo ships an `add-words` Skill (`skills/add-words/`) that adds words via the authenticated REST API. It reads `WORD_MEMORY_BASE_URL` + `WORD_MEMORY_API_TOKEN` (token needs `words:write`) and **must not touch SQLite or print the token**. API discovery is at `/.well-known/word-review-api` and the authenticated `/api/v1/capabilities`.

## Configuration & startup

`Settings.from_env()` (`core/config.py`, `lru_cache`d) is the single source for config. Required for startup: `API_TOKEN_PEPPER` or `API_TOKEN_PEPPER_FILE` (≥32 bytes). Production also needs `DATABASE_URL`, `PUBLIC_BASE_URL`, `TRUSTED_HOSTS`, `TRUSTED_PROXY_CIDRS`. AI enrichment accepts `AI_BASE_URL`, `AI_MODEL`, and either `AI_API_KEY_FILE` (preferred; file wins) or `AI_API_KEY`. Cloud TTS accepts `TTS_BASE_URL` (default `https://api.xiaomimimo.com/v1`), `TTS_MODEL` (default `mimo-v2.5-tts`), `TTS_VOICE` (default `Chloe`), `TTS_AUDIO_DIR`, `TTS_TIMEOUT_SECONDS`, and either `TTS_API_KEY_FILE` (preferred; file wins) or `TTS_API_KEY`. `TRUSTED_LOCAL_WEB` defaults to `false`. Wildcard CORS origins are rejected. Set `LOG_LEVEL=DEBUG` to log route templates, latency, dictionary misses, and actor type — tokens and request bodies are never logged.

**Web login (optional):** set `WEB_LOGIN_REQUIRED=true` + `WEB_ADMIN_PASSWORD` (or `WEB_ADMIN_PASSWORD_FILE`) to expose a `/login` page backed by a signed session cookie (`wm_session`, secret = `SESSION_SECRET(_FILE)`, defaulting to the token pepper). Optional: `WEB_ADMIN_USERNAME` (default `admin`), `SESSION_MAX_AGE` (default 7d). With `WEB_LOGIN_REQUIRED=true`, the proxy/local web-admin branches are disabled — only the cookie login (and bearer tokens) authenticate. Provision/rotate web credentials with `scripts/set_web_password.py`.

## Conventions to follow

- Keep the four-layer split: routes call services; services own DB writes and transactions; raise `AppError` for any business failure.
- New mutable resource? Add a `version` column and require `expected_version` on writes.
- New write route? Decide on `Idempotency-Key` (header, for whole-request replay) vs `client_event_id` (per-item dedup), wire `claim()`/`complete()`, and **add the entry to `REQUIRED_SCOPES` in `main.py`**.
- New enum value or constraint? Add it in `models/entities.py` (DB-level `CheckConstraint`), `schemas/contracts.py` (Pydantic `Literal`), and `src/types/domain.ts`.
- After touching any request/response shape or scope, regenerate `backend/contracts/openapi.yaml` with `export_openapi.py`.
- The deployment is single-tenant (one owner): all web logins share one word library — `admin` owns it, `student` accounts can only do online review. There is no per-user data isolation; don't add multi-tenant assumptions.
- New web role? Add it to `ROLE_SCOPES` in `core/auth.py`, declare it in `WebRole` (`schemas/contracts.py` + `src/types/domain.ts`), and gate routes with `meta.roles` in `frontend/src/router/index.ts`.
- Login/user-management routes (`/api/v1/auth/*`, `/api/v1/users/*`) are NOT in `REQUIRED_SCOPES` — `/auth/*` is public/session-self-managed, `/users/*` is admin-only via the `require_web_admin` dependency. Keep `ALL_SCOPES` (the API-client scope universe) free of any `users:manage`-style scope.
