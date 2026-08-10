# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project context

Single-user, NAS-deployed vocabulary practice system (单词记忆辅助系统). UI and design docs are in Chinese; code and identifiers are in English. The primary loop is **offline**: generate a printable word worksheet, review on paper, then come back to the web app to record three-state results (`known` / `unknown` / `skipped`). Online flashcard review is a secondary, occasional path. Both paths share the same data model and result-recording rules.

Development is staged into six phases with frozen decisions under `docs/design/`; implementation plans and execution records live under `docs/superpowers/`. Phases 1–6 are implemented. Each phase doc or enhancement spec defines the completion gates for its scope.

### Production image, CI, and NAS deploy (phase 5)

- **Image**: repo-root `Dockerfile` is multi-stage — `node:22-alpine` builds the Vue SPA (`npm ci` + `npm run build`), `python:3.12-slim` runs FastAPI serving API + the built SPA. Base images are pinned to a version+digest. Runtime is non-root UID/GID 10001 (only `/app/data` writable). `backend/docker-entrypoint.sh` runs `alembic upgrade head` before `uvicorn`, so `/healthz/ready` passes on a fresh DB. The runtime stage installs weasyprint system libs + `fonts-noto-cjk` so the phase-4 `/recitation` PDF endpoint works.
- **Locked deps**: `backend/requirements.lock` is a hashed, fully-pinned lockfile (includes the `[pdf]` extra); the Dockerfile installs it with `pip install --require-hashes`. Regenerate with `pip-compile --generate-hashes --extra pdf -o requirements.lock pyproject.toml` (Python 3.12).
- **CI**: `.github/workflows/ci.yml` runs gates on push-to-main and PR (backend `ruff check app tests` + `pytest`; frontend `typecheck` + vitest + build; OpenAPI-contract drift check; docker build + container smoke test of `/healthz/*` + SPA deep link + API-not-swallowed; Trivy HIGH/CRITICAL scan). Only push-to-main publishes `ghcr.io/huang8604/vocab-app:latest` + `sha-<short>` to GHCR. Third-party actions are pinned to commit SHAs.
- **Push monitoring**: use `./scripts/push-and-monitor-actions.sh` instead of a bare `git push`. It pushes HEAD, waits for the exact commit's push-triggered `ci.yml` run, and exits only after success, failure, or timeout. Pass git push options after `--`; use `--skip-push --sha <commit>` to monitor an existing push.
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

Words can carry server-generated MP3 pronunciation metadata (`audio_path`, `audio_format`, `audio_voice`, `audio_generated_at`, `audio_bytes`). `services/tts.py` supports **two providers** selected by `TTS_PROVIDER` (`mimo` default, or `volc`): `synthesize_word_mp3(text, *, provider=None)` returns `(bytes, effective_voice)` and **falls back across providers** — it tries the selected one first, and on not-configured / `TTS_PROVIDER_ERROR` retries the other configured provider (both unconfigured → `409 TTS_NOT_CONFIGURED`). `generate_word_audio(..., provider=None)` records the effective `audio_voice` so the UI shows which model produced each clip. Vue never receives any provider key.

- **mimo**: OpenAI-style `POST {TTS_BASE_URL}/chat/completions` with `modalities:["text","audio"]`; base64 mp3 in `choices[0].message.audio.data`. The style `PROMPT` requests clear, forceful British English with a brief pause before/after.
- **volc** (豆包 `doubao-seed-tts-2.0`): the **agent-plan** endpoint `POST {VOLC_TTS_BASE_URL}/api/v3/plan/tts/unidirectional?api_key=<key>` (the api key MUST go in the query string — this key type 401s on the standard `/api/v3/tts/unidirectional`) with header `X-Api-Resource-Id: seed-tts-2.0` and body `{"user":{"uid"},"req_params":{text, speaker (string), audio_params:{format, sample_rate, speech_rate, loudness_rate}, additions: <JSON STRING>}}` — three verified shape rules: (1) `speaker` must be a 豆包语音合成模型2.0 voice (`*_uranus_bigtts`, default `zh_female_yingyujiaoxue_uranus_bigtts` = Tina老师 2.0, 教育场景/中文+英式英语; 1.0 ids `BVxxx`/`*_moon_bigtts`/`*_mars_bigtts` → `55000000 resource ID is mismatched`); (2) `additions` is typed "jsonstring" — pass `json.dumps({"silence_duration": ms})`, not an object (object → unmarshal error); (3) the success response is HTTP-chunked NDJSON (one `{code,message,data}` event per line; base64 MP3 fragments in `data`, terminated by `code=20000000`) — `_decode_audio` reassembles it. `VOLC_TTS_SPEECH_RATE` (<0 slower → 平稳耐心), `VOLC_TTS_LOUDNESS_RATE` (>0 louder → 有力清晰), `VOLC_TTS_SILENCE_MS` (trailing silence → 留白) tune the voice; leading silence relies on the MP3 encoder delay (~100ms) + the dictation engine's per-word gap. For British English the 2.0 list only has Tina老师; American English has many (`en_*_uranus_bigtts`). Requires the model be activated (配置模型 + 开启超额后付费).

Admin audio routes (all `words:*`, never exposed to students — students lack `words:read`): `POST /words/{id}/audio` accepts an optional `provider`; `POST /words/audio/generate-missing` and `POST /words/audio/regenerate-all` enqueue to the background worker (return `{queued,total,provider}`) — `generate-missing` picks audio-less words, `regenerate-all` force-regenerates **every** non-deleted word; `POST /words/audio/generate-numbers` generates the dictation **number-announcement** clips (`"number 1"` … `"number 50"`, 豆包 preferred via default `provider="volc"`, `force` regenerates all 50); `GET /words/audio/providers` reports configured providers + the current default; `GET /words/audio/progress` returns `{state,total,completed,failed,pending}` for the progress bar (polled by the word-library UI while `state=="running"`). `/api/v1/practice-sessions/{session_id}/items/{item_id}/audio` exposes one session item's MP3 under `practice:read` so dictation can play it. **Number-announcement audio** (`services/number_audio.py`): standalone MP3 assets — **not words**, no DB record — stored under `audio_dir()/numbers/number-{n}.mp3`, generated once via `synthesize_word_mp3(f"number {n}", provider="volc")` (mimo fallback) and served read-only by `GET /api/v1/dictation/numbers/{n}/audio` (`practice:read`; 404 if not yet generated). Online dictation plays `"number {position}"` before each word (1-based, capped at 50; once per word, not per repeat) — toggle `announceNumber` in `DictationSettings`; the player chains number→word on the same unlocked `<audio>` element and silently skips the number if it 404s/errors. **Background generation**: `services/audio_worker.py` runs a single daemon thread (queue + dedup + run counters) processing `_AudioJob(kind="word"|"number", key, force, provider)`; `/words/import` auto-enqueues created words when `TTS_AUTO_GENERATE_ON_IMPORT=true` (default) and any provider is configured — the import worker does this on completion and the count surfaces in the import-progress snapshot (`audio_generation.queued`), not the POST response. Process restart interrupts it; recover via the regenerate buttons. Generated files go under `TTS_AUDIO_DIR` (else beside the SQLite DB under `audio/`; production `/app/data/audio`) via temp file + fsync + atomic `os.replace`. Online dictation plays the server MP3 first and falls back to browser `speechSynthesis`. Tests must mock `app.services.tts.synthesize_word_mp3` (or `tts._PROVIDERS`) and keep `TTS_BASE_URL`/`TTS_API_KEY`/`VOLC_TTS_API_KEY` empty by default.

**Local dictionary shared audio cache:** the System page controls `services/dictionary_audio.py` through `/api/v1/system/dictionary-audio/{progress,start,pause,resume}` (web-admin only). It walks every normalized key in `dictionary-index.json`, stores MP3s under `audio_dir()/dictionary/`, and keeps cache metadata plus the singleton run state in `audio_dir()/dictionary-audio.sqlite3`. Progress, pause, ordinary-failure retry, quota wait, and the next scheduled scan survive restarts. `TTS_QUOTA_EXHAUSTED` pauses remote calls for five hours by default; ordinary failures retry after five minutes; completed caches scan hourly for new dictionary entries. Creating or restoring a `Word` attaches an existing shared clip by `normalized_en_word`, so a dictionary hit does not consume TTS again. Optional tuning: `DICTIONARY_AUDIO_RETRY_SECONDS`, `DICTIONARY_AUDIO_SCAN_SECONDS`, and `DICTIONARY_AUDIO_QUOTA_WAIT_SECONDS` (defaults `300`, `3600`, `18000`).

**Background word import** (`services/import_worker.py`): a real `POST /words/import` is parsed + validated synchronously (syntax/size, `tags` default-tag merge, `conflict_policy=reject` zero-write pre-scan, and an in-file-duplicate check that 422s under reject/update), then **enqueued** — the response is an immediate `ImportProgress` snapshot, not the result. The worker runs one daemon thread; each row runs in its **own session + own commit** (`run_import_row`), so a slow enrichment or per-row error no longer rolls back the batch — successful rows persist, failures are counted and skipped (process restart interrupts; the operator re-triggers). `dry_run` stays a synchronous preview reusing `run_import_row(dry_run=True)`. `unresolved_policy` only controls whether AI is attempted (`ai` vs not); unresolved words are never written, only counted + listed. `GET /words/import/progress` returns `{state,total,processed,created,updated,skipped,failed,unresolved,unresolved_words,resolved,dictionary_matches,audio_generation,finished}` (polled by the word-library UI while running). `tags` form field = comma-separated default tags unioned into every row (txt/csv/json). The `Idempotency-Key` (when sent) is finalized from the worker via `complete_by_key` so a replay returns the final result. **Batch operations** (`words:write`, per-word optimistic lock + partial success, single `Idempotency-Key`): `POST /words/batch/delete` `{items:[{id,expected_version}]}` → `{deleted,conflicts,missing}`; `POST /words/batch/tags` `{items,tags}` → `{updated,conflicts,missing}` (unions tags onto existing); `POST /words/batch/audio` `{word_ids,provider?}` enqueues to the audio worker (`409 TTS_NOT_CONFIGURED` if no provider); `POST /words/batch/reset-progress` `{word_ids}` → `{reset}`. The word-library UI renders a batch action bar when rows are selected.

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

The `/system` route (`meta.roles: ['admin']`) is the admin console: local-dictionary shared audio generation (persistent progress, pause/resume, retry/quota wait), API-client/token management (create, rotate, revoke, adjust scopes — the plaintext token is shown only on create/rotate), and one-click SQLite full-backup download (`GET /api/v1/system/backup` streams a `.db` snapshot). It replaces the CLI lifecycle scripts for day-to-day admin.

## Frontend conventions

- Axios `apiClient` (`src/api/client.ts`) is fixed at `/api/v1`; callers unwrap the envelope with `unwrap()` to get `.data`, and treat export endpoints as `Blob`. `ApiError` normalizes all failures (status → Chinese message map); `.isConflict` / `.isCanceled` helpers drive UI.
- **`src/types/domain.ts` is the source of truth for response types**, not OpenAPI — the backend's success schemas are not fully described, and types are validated by API unit tests + e2e mocks instead.
- Routing in `src/router/index.ts`; each nav route carries `meta` used for labels and document title. Responsive breakpoints in `src/styles/breakpoints.css`; print rules in `src/styles/print.css`.
- `newEventId()` generates the `client_event_id` for each review submission; `formatPhonetic` (`@/utils/formatPhonetic`) wraps a raw phonetic string in `/ /` for display (shared across worksheet, review, and recitation views).
- **Auth**: `useAuthStore` (`stores/auth.ts`) holds the logged-in identity (`username`/`role`); the router `beforeEach` awaits `fetchMe()` once, then enforces each route's `meta.roles` (`admin` sees everything, `student` only `/review`; `/system` is `['admin']`). `apiClient` uses `withCredentials` and, on a non-`/auth/*` 401, clears the store and redirects to `/login`. Login is a server-set session cookie — no token lives in JS.
- **Audio**: word-library controls call `src/api/words.ts` to generate MP3s and play `/api/v1/words/{id}/audio`; `OnlineDictation.vue` passes practice-item audio URLs to `useDictationPlayer`, which tries server MP3 first and falls back to `speechSynthesis` without exposing any TTS key in JS.

## External Skills

The repo ships four self-contained Skills under `skills/`: `add-words` (`words:write`), `import-words` (`words:write` + `words:read`), `generate-worksheet` (`practice:generate`), and `record-review-results` (`practice:read` + `reviews:write`). They read `WORD_MEMORY_BASE_URL` + `WORD_MEMORY_API_TOKEN`, **must not touch SQLite or print the token**, and use only Python's standard library. `README.md` is the installation/token guide; each Skill's `SKILL.md` owns its task workflow. API discovery is at `/.well-known/word-review-api` and the authenticated `/api/v1/capabilities`.

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
