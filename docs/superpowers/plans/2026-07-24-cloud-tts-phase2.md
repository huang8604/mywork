# Cloud TTS Audio Phase 2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add server-generated mimo MP3 audio for words, word-library audio controls, and online-dictation playback that prefers stored cloud MP3 while preserving student-only `/review` permissions.

**Architecture:** Backend stores MP3 files under the app data directory and stores only audio metadata on `Word`. Admin word routes generate/read audio using `words:*` scopes, while a separate practice-session item audio route uses `practice:read` so students can hear audio without gaining word-library access. Frontend word-library buttons call generation APIs; dictation player tries `<audio>` URL first and falls back to existing `speechSynthesis`.

**Tech Stack:** FastAPI, SQLAlchemy/Alembic, SQLite file storage, Pydantic strict schemas, Vue 3, Element Plus, Vitest/jsdom.

---

## File Structure

- `backend/app/models/entities.py` — add `Word.audio_*` columns.
- `backend/migrations/versions/0004_word_audio.py` — add idempotent audio metadata columns.
- `backend/app/core/config.py` — add TTS env fields and `tts_enabled`/audio-dir helpers.
- `backend/app/services/tts.py` — mimo HTTP call and base64 MP3 extraction; no DB.
- `backend/app/services/words.py` — generate audio, resolve safe audio file path, batch generate missing.
- `backend/app/services/serializers.py` — expose audio metadata in `word_data`.
- `backend/app/schemas/contracts.py` — add `WordAudioGenerateRequest` and `WordAudioBatchGenerateRequest`.
- `backend/app/api/words.py` — add admin word audio GET/POST and batch generate routes.
- `backend/app/api/practice.py` — add `GET /practice-sessions/{session_id}/items/{item_id}/audio`.
- `backend/app/main.py` — add required scopes for new routes.
- `backend/app/api/health.py`, `backend/docker-entrypoint.sh` — revision `0004`.
- `backend/contracts/openapi.yaml` — regenerated.
- `backend/tests/test_word_audio.py` — backend tests with mocked TTS.
- `frontend/src/types/domain.ts` — add audio fields and batch result types.
- `frontend/src/api/words.ts` — add audio URL and generation APIs.
- `frontend/src/api/practiceSessions.ts` — add session item audio URL helper.
- `frontend/src/components/ResponsiveWordList.vue`, `frontend/src/components/WordCard.vue` — add row/card audio buttons and emits.
- `frontend/src/views/WordsView.vue` — wire playback/generate/batch controls.
- `frontend/src/composables/useDictationPlayer.ts`, `frontend/src/views/review/OnlineDictation.vue` — cloud MP3 playback before speech fallback.
- `frontend/tests/unit/dictationAudio.spec.ts` or `dictationEngine.spec.ts` extension — cloud/fallback/cancel tests.
- `CLAUDE.md`, `deploy/README.md` — document TTS config and audio backup caveat.

---

### Task 1: Backend audio metadata + schemas + serializer

**Files:**
- Modify: `backend/app/models/entities.py`
- Create: `backend/migrations/versions/0004_word_audio.py`
- Modify: `backend/app/schemas/contracts.py`
- Modify: `backend/app/services/serializers.py`
- Modify: `backend/app/api/health.py`
- Modify: `backend/docker-entrypoint.sh`
- Test: covered by Task 4 tests after service/routes exist.

- [ ] **Step 1: Add columns to `Word`**

Add after `example_sentence`:

```python
audio_path: Mapped[str | None] = mapped_column(String(255), nullable=True)
audio_format: Mapped[str | None] = mapped_column(String(16), nullable=True)
audio_voice: Mapped[str | None] = mapped_column(String(64), nullable=True)
audio_generated_at: Mapped[str | None] = mapped_column(String(32), nullable=True)
audio_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
```

- [ ] **Step 2: Write migration `0004_word_audio.py`**

Use idempotent guards:

```python
"""Add word audio metadata columns."""

from alembic import op
import sqlalchemy as sa

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def _columns(table: str) -> set[str]:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return {col["name"] for col in inspector.get_columns(table)}


def upgrade() -> None:
    cols = _columns("words")
    with op.batch_alter_table("words") as batch:
        if "audio_path" not in cols:
            batch.add_column(sa.Column("audio_path", sa.String(length=255), nullable=True))
        if "audio_format" not in cols:
            batch.add_column(sa.Column("audio_format", sa.String(length=16), nullable=True))
        if "audio_voice" not in cols:
            batch.add_column(sa.Column("audio_voice", sa.String(length=64), nullable=True))
        if "audio_generated_at" not in cols:
            batch.add_column(sa.Column("audio_generated_at", sa.String(length=32), nullable=True))
        if "audio_bytes" not in cols:
            batch.add_column(sa.Column("audio_bytes", sa.Integer(), nullable=True))


def downgrade() -> None:
    cols = _columns("words")
    with op.batch_alter_table("words") as batch:
        for name in ["audio_bytes", "audio_generated_at", "audio_voice", "audio_format", "audio_path"]:
            if name in cols:
                batch.drop_column(name)
```

- [ ] **Step 3: Add schemas**

In `contracts.py` add near word schemas:

```python
class WordAudioGenerateRequest(StrictModel):
    force: bool = False


class WordAudioBatchGenerateRequest(StrictModel):
    limit: int = Field(default=50, ge=1, le=100)
```

- [ ] **Step 4: Add serializer fields**

In `word_data()`, include:

```python
"audio_path": word.audio_path,
"audio_format": word.audio_format,
"audio_voice": word.audio_voice,
"audio_generated_at": word.audio_generated_at,
"audio_bytes": word.audio_bytes,
```

- [ ] **Step 5: Update readiness revision**

Change health expected revision from `"0003"` to `"0004"`; update entrypoint comments from `0003` to `0004`.

- [ ] **Step 6: Run backend import smoke**

Run:

```bash
cd backend && python -m py_compile app/models/entities.py app/schemas/contracts.py app/services/serializers.py
```

Expected: no output.

- [ ] **Step 7: Commit**

```bash
git add backend/app/models/entities.py backend/migrations/versions/0004_word_audio.py backend/app/schemas/contracts.py backend/app/services/serializers.py backend/app/api/health.py backend/docker-entrypoint.sh
git commit -m "feat(audio): add word audio metadata"
```

---

### Task 2: TTS config and synthesis service

**Files:**
- Modify: `backend/app/core/config.py`
- Create: `backend/app/services/tts.py`
- Test: `backend/tests/test_word_audio.py` in Task 4.

- [ ] **Step 1: Add config fields**

Add to `Settings` dataclass:

```python
tts_base_url: str
tts_api_key_file: str | None
tts_api_key: str
tts_model: str
tts_voice: str
tts_audio_dir: str
tts_timeout_seconds: float
```

In `from_env()`, mirror AI key file-wins:

```python
tts_api_key_file = os.getenv("TTS_API_KEY_FILE")
if tts_api_key_file:
    tts_api_key = Path(tts_api_key_file).read_text(encoding="utf-8").strip()
    if not tts_api_key:
        raise ValueError("TTS_API_KEY_FILE must not be empty")
else:
    tts_api_key = os.getenv("TTS_API_KEY", "").strip()
```

Set values:

```python
tts_base_url=os.getenv("TTS_BASE_URL", "https://api.xiaomimimo.com/v1").rstrip("/"),
tts_api_key_file=tts_api_key_file,
tts_api_key=tts_api_key,
tts_model=os.getenv("TTS_MODEL", "mimo-v2.5-tts"),
tts_voice=os.getenv("TTS_VOICE", "Chloe"),
tts_audio_dir=os.getenv("TTS_AUDIO_DIR", "").strip(),
tts_timeout_seconds=float(os.getenv("TTS_TIMEOUT_SECONDS", "60")),
```

Add property:

```python
@property
def tts_enabled(self) -> bool:
    return bool(self.tts_base_url and self.tts_api_key)
```

- [ ] **Step 2: Create `services/tts.py`**

Implement with stdlib `urllib.request` (no new dependency):

```python
from __future__ import annotations

import base64
import json
import logging
import urllib.error
import urllib.request

from app.core.config import Settings, get_settings
from app.core.errors import AppError

log = logging.getLogger(__name__)

PROMPT = "Pronounce this English word clearly and naturally for vocabulary dictation."


def synthesize_word_mp3(text: str, *, settings: Settings | None = None) -> bytes:
    settings = settings or get_settings()
    if not settings.tts_enabled:
        raise AppError(409, "TTS_NOT_CONFIGURED", "TTS 尚未配置")
    payload = {
        "model": settings.tts_model,
        "modalities": ["text", "audio"],
        "audio": {"voice": settings.tts_voice, "format": "mp3"},
        "messages": [
            {"role": "user", "content": PROMPT},
            {"role": "assistant", "content": text},
        ],
    }
    req = urllib.request.Request(
        f"{settings.tts_base_url}/chat/completions",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {settings.tts_api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=settings.tts_timeout_seconds) as response:
            raw = response.read()
        data = json.loads(raw)
        encoded = data["choices"][0]["message"]["audio"]["data"]
        audio = base64.b64decode(encoded)
    except (urllib.error.URLError, TimeoutError, KeyError, IndexError, TypeError, ValueError) as exc:
        log.warning("TTS provider failed: %s", exc.__class__.__name__)
        raise AppError(502, "TTS_PROVIDER_ERROR", "TTS 供应商调用失败") from exc
    if not audio:
        raise AppError(502, "TTS_PROVIDER_ERROR", "TTS 供应商未返回音频")
    return audio
```

- [ ] **Step 3: Run compile smoke**

```bash
cd backend && python -m py_compile app/core/config.py app/services/tts.py
```

- [ ] **Step 4: Commit**

```bash
git add backend/app/core/config.py backend/app/services/tts.py
git commit -m "feat(audio): add TTS synthesis service"
```

---

### Task 3: Word audio service methods and backend routes

**Files:**
- Modify: `backend/app/services/words.py`
- Modify: `backend/app/api/words.py`
- Modify: `backend/app/api/practice.py`
- Modify: `backend/app/main.py`

- [ ] **Step 1: Add service helpers**

Add functions to `services/words.py`:

```python
def audio_dir(settings: Settings | None = None) -> Path:
    settings = settings or get_settings()
    if settings.tts_audio_dir:
        return Path(settings.tts_audio_dir)
    db_url = settings.database_url
    if db_url.startswith("sqlite:///"):
        return Path(db_url.removeprefix("sqlite:///")).resolve().parent / "audio"
    return Path("data/audio").resolve()


def _audio_filename(word: Word, settings: Settings) -> str:
    digest = hashlib.sha256(f"{word.en_word}|{settings.tts_model}|{settings.tts_voice}".encode("utf-8")).hexdigest()[:12]
    return f"word-{word.id}-{digest}.mp3"


def word_audio_file(word: Word, settings: Settings | None = None) -> Path | None:
    if not word.audio_path:
        return None
    root = audio_dir(settings)
    candidate = (root / word.audio_path).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError:
        return None
    return candidate if candidate.exists() else None
```

Then implement:

```python
def generate_word_audio(db: Session, word_id: int, *, force: bool = False) -> Word:
    word = get_word(db, word_id, include_deleted=False)
    if word.audio_path and not force and word_audio_file(word):
        return word
    settings = get_settings()
    audio = synthesize_word_mp3(word.en_word, settings=settings)
    root = audio_dir(settings)
    root.mkdir(parents=True, exist_ok=True)
    filename = _audio_filename(word, settings)
    final = root / filename
    fd, tmp_name = tempfile.mkstemp(prefix=f".{filename}.", suffix=".tmp", dir=root)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(audio)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, final)
    except OSError as exc:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise AppError(503, "AUDIO_STORAGE_ERROR", "音频文件写入失败") from exc
    old_path = word.audio_path
    word.audio_path = filename
    word.audio_format = "mp3"
    word.audio_voice = settings.tts_voice
    word.audio_generated_at = utc_text()
    word.audio_bytes = len(audio)
    word.version += 1
    word.updated_at = utc_text()
    if old_path and old_path != filename:
        old_file = (root / old_path).resolve()
        try:
            if old_file.exists() and old_file.relative_to(root.resolve()):
                old_file.unlink()
        except (OSError, ValueError):
            pass
    return word
```

Add batch result function returning a dict.

- [ ] **Step 2: Add word audio routes**

In `api/words.py`, import `FileResponse`, schemas, service functions. Add before `/{word_id}` routes to avoid path conflicts:

```python
@router.post("/audio/generate-missing")
def generate_missing_audio(...): ...

@router.get("/{word_id}/audio")
def get_audio(...): ...

@router.post("/{word_id}/audio")
def generate_audio(...): ...
```

Use `claim()`/`complete()` on POSTs, `_commit(db)`, `add_audit`, and `envelope()` matching existing route style.

- [ ] **Step 3: Add practice item audio route**

In `api/practice.py` add:

```python
@router.get("/practice-sessions/{session_id}/items/{item_id}/audio")
def practice_item_audio(session_id: int, item_id: int, db: Session = Depends(get_db)):
    session = _session(db, session_id)
    item = db.get(PracticeSessionItem, item_id)
    if item is None or item.session_id != session.id:
        raise not_found("PracticeSessionItem", item_id)
    word = db.get(Word, item.word_id)
    path = word_audio_file(word) if word else None
    if path is None:
        raise AppError(404, "AUDIO_NOT_FOUND", "尚未生成音频")
    return FileResponse(path, media_type="audio/mpeg", headers={"Content-Disposition": "inline"})
```

- [ ] **Step 4: Update `REQUIRED_SCOPES`**

Add:

```python
("GET", "/api/v1/words/{word_id}/audio"): ["words:read"],
("POST", "/api/v1/words/{word_id}/audio"): ["words:write"],
("POST", "/api/v1/words/audio/generate-missing"): ["words:write"],
("GET", "/api/v1/practice-sessions/{session_id}/items/{item_id}/audio"): ["practice:read"],
```

- [ ] **Step 5: Commit after tests from Task 4 pass**

Commit together with tests.

---

### Task 4: Backend tests for audio routes and services

**Files:**
- Create: `backend/tests/test_word_audio.py`

- [ ] **Step 1: Write tests**

Test content outline:

```python
from __future__ import annotations

from pathlib import Path
from app.core.config import get_settings
from conftest import create_word

MP3 = b"\xff\xf3\x84\xc4" + b"audio" * 20


def _enable_tts(monkeypatch, tmp_path):
    monkeypatch.setenv("TTS_API_KEY", "test-key")
    monkeypatch.setenv("TTS_BASE_URL", "https://example.invalid/v1")
    monkeypatch.setenv("TTS_AUDIO_DIR", str(tmp_path / "audio"))
    get_settings.cache_clear()


def test_audio_generation_requires_tts_config(client):
    word = create_word(client, {"en_word": "camera", "cn_meaning": "相机", "tags": []})
    r = client.post(f"/api/v1/words/{word['id']}/audio", headers={"Idempotency-Key": "audio-missing"}, json={})
    assert r.status_code == 409
    assert r.json()["code"] == "TTS_NOT_CONFIGURED"


def test_generate_and_get_word_audio(client, monkeypatch, tmp_path):
    _enable_tts(monkeypatch, tmp_path)
    import app.services.tts as tts
    calls = []
    monkeypatch.setattr(tts, "synthesize_word_mp3", lambda text, *, settings=None: calls.append(text) or MP3)
    word = create_word(client, {"en_word": "camera", "cn_meaning": "相机", "tags": []})
    r = client.post(f"/api/v1/words/{word['id']}/audio", headers={"Idempotency-Key": "audio-1"}, json={})
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    assert data["audio_format"] == "mp3"
    assert data["audio_voice"] == "Chloe"
    assert data["audio_bytes"] == len(MP3)
    assert calls == ["camera"]
    audio = client.get(f"/api/v1/words/{word['id']}/audio")
    assert audio.status_code == 200
    assert audio.headers["content-type"].startswith("audio/mpeg")
    assert audio.content == MP3
```

Also add tests for force=false, force=true, batch order/has_more/failures, and student word vs practice audio authorization.

- [ ] **Step 2: Run failing tests**

```bash
cd backend && pytest tests/test_word_audio.py -q
```

Expected before Task 3 implementation: failures about missing routes/fields.

- [ ] **Step 3: Implement Task 3 code**

Implement service + routes + scopes.

- [ ] **Step 4: Run backend audio tests**

```bash
cd backend && pytest tests/test_word_audio.py -q
```

Expected: all pass.

- [ ] **Step 5: Run backend focused gates**

```bash
cd backend && ruff check app tests && pytest -q
```

Expected: all pass.

- [ ] **Step 6: Commit backend audio implementation**

```bash
git add backend/app/services/words.py backend/app/api/words.py backend/app/api/practice.py backend/app/main.py backend/tests/test_word_audio.py
git commit -m "feat(audio): generate and serve word MP3 audio"
```

---

### Task 5: OpenAPI contract

**Files:**
- Modify: `backend/contracts/openapi.yaml`

- [ ] **Step 1: Regenerate OpenAPI**

```bash
cd backend && python scripts/export_openapi.py
```

- [ ] **Step 2: Check contract drift command**

```bash
cd backend && git diff -- contracts/openapi.yaml | head -80
```

Expected: new audio endpoints/schemas/scopes only.

- [ ] **Step 3: Commit**

```bash
git add backend/contracts/openapi.yaml
git commit -m "chore(contracts): export audio routes"
```

---

### Task 6: Frontend word audio APIs and types

**Files:**
- Modify: `frontend/src/types/domain.ts`
- Modify: `frontend/src/api/words.ts`
- Modify: `frontend/src/api/practiceSessions.ts`

- [ ] **Step 1: Add types**

Extend `Word`:

```ts
audio_path: string | null; audio_format: string | null; audio_voice: string | null
audio_generated_at: string | null; audio_bytes: number | null
```

Add:

```ts
export interface WordAudioBatchFailure { word_id: number; en_word: string; message: string }
export interface WordAudioBatchResult { requested: number; generated: number; skipped: number; failed: number; failures: WordAudioBatchFailure[]; has_more: boolean }
```

- [ ] **Step 2: Add API helpers**

In `words.ts`:

```ts
export function wordAudioUrl(wordId: number) { return `/api/v1/words/${wordId}/audio` }
export async function generateWordAudio(wordId: number, force = false) { ... }
export async function generateMissingWordAudio(limit = 50) { ... }
```

Use `newEventId()` for `Idempotency-Key`.

In `practiceSessions.ts`:

```ts
export function sessionItemAudioUrl(sessionId: number, itemId: number) {
  return `/api/v1/practice-sessions/${sessionId}/items/${itemId}/audio`
}
```

- [ ] **Step 3: Run typecheck**

```bash
cd frontend && npm run typecheck
```

- [ ] **Step 4: Commit**

```bash
git add frontend/src/types/domain.ts frontend/src/api/words.ts frontend/src/api/practiceSessions.ts
git commit -m "feat(audio): add frontend audio APIs"
```

---

### Task 7: Word-library audio buttons and batch generation UI

**Files:**
- Modify: `frontend/src/components/ResponsiveWordList.vue`
- Modify: `frontend/src/components/WordCard.vue`
- Modify: `frontend/src/views/WordsView.vue`
- Test: optional focused component tests if time; full frontend suite required.

- [ ] **Step 1: Add emits and buttons in list/card**

Add emits `playAudio` and `generateAudio`.

Desktop action buttons:

```vue
<el-button link type="primary" :disabled="!row.audio_path" @click="$emit('play-audio', row)">播放音频</el-button>
<el-button link type="primary" @click="$emit('generate-audio', row)">{{ row.audio_path ? '重生成' : '生成音频' }}</el-button>
```

Mobile card equivalent.

- [ ] **Step 2: Wire `WordsView` handlers**

Add imports and state:

```ts
import { generateMissingWordAudio, generateWordAudio, wordAudioUrl } from '@/api/words'
const audio = new Audio()
const audioBusy = ref<number | null>(null)
const batchAudio = ref({ running: false, generated: 0, failed: 0, batch: 0, stop: false })
```

Handlers:

```ts
async function playAudio(word: Word) { ... new Audio(wordAudioUrl(word.id)).play() ... }
async function generateAudio(word: Word) { ... await generateWordAudio(word.id, Boolean(word.audio_path)); await load() ... }
async function generateMissingAudio() { while (!batchAudio.value.stop) { const r = await generateMissingWordAudio(50); ... if (!r.has_more) break } }
```

- [ ] **Step 3: Add top button**

In button row:

```vue
<el-button :loading="batchAudio.running" @click="generateMissingAudio">一键生成音频</el-button>
<el-button v-if="batchAudio.running" @click="batchAudio.stop=true">停止</el-button>
```

- [ ] **Step 4: Run frontend gates**

```bash
cd frontend && npm run typecheck && npm test && npm run build
```

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/ResponsiveWordList.vue frontend/src/components/WordCard.vue frontend/src/views/WordsView.vue
git commit -m "feat(audio): add word library audio controls"
```

---

### Task 8: Dictation cloud MP3 playback fallback

**Files:**
- Modify: `frontend/src/composables/useDictationPlayer.ts`
- Modify: `frontend/src/views/review/OnlineDictation.vue`
- Modify: `frontend/tests/unit/dictationEngine.spec.ts` or create `frontend/tests/unit/dictationAudio.spec.ts`

- [ ] **Step 1: Extend player options**

Change `useDictationPlayer({ texts })` to support optional:

```ts
items?: () => Array<{ itemId: number; text: string }>
audioUrlFor?: (index: number) => string | null
```

- [ ] **Step 2: Add audio-first play**

In `makePlay`, before speech fallback:

```ts
const audioUrl = opts.audioUrlFor?.(index.value)
if (audioUrl) {
  const audio = new Audio(audioUrl)
  audio.onended = hooks.onEnd
  audio.onerror = () => fallbackSpeech(text, hooks)
  audio.play().catch(() => fallbackSpeech(text, hooks))
  return () => { audio.pause(); audio.removeAttribute('src'); audio.load() }
}
return fallbackSpeech(text, hooks)
```

Keep old speech logic in `fallbackSpeech`.

- [ ] **Step 3: Wire OnlineDictation**

Import `sessionItemAudioUrl` and pass:

```ts
const player = useDictationPlayer({
  texts,
  audioUrlFor: i => {
    const item = props.session.items?.[i]
    return item ? sessionItemAudioUrl(props.session.session_id, item.item_id) : null
  },
})
```

- [ ] **Step 4: Add tests**

Mock `globalThis.Audio` to resolve/reject play; verify cloud success avoids speech and play reject falls back.

- [ ] **Step 5: Run frontend gates**

```bash
cd frontend && npm run typecheck && npm test && npm run build
```

- [ ] **Step 6: Commit**

```bash
git add frontend/src/composables/useDictationPlayer.ts frontend/src/views/review/OnlineDictation.vue frontend/tests/unit/dictationAudio.spec.ts
git commit -m "feat(review): play cloud audio before speech fallback"
```

---

### Task 9: Documentation and final verification

**Files:**
- Modify: `CLAUDE.md`
- Modify: `deploy/README.md`

- [ ] **Step 1: Document TTS config**

Add TTS env vars, storage path, route/scopes, and DB-backup caveat.

- [ ] **Step 2: Full verification**

Backend container command (per project guidance):

```bash
docker exec myword-lan-backend sh -lc 'cd /workspace/backend && export TRUSTED_HOSTS=localhost,127.0.0.1,testserver PUBLIC_BASE_URL=http://localhost:8000 CORS_ORIGINS=http://localhost:8000 && ruff check app tests && pytest -q && python scripts/export_openapi.py && git diff --exit-code -- contracts/openapi.yaml'
```

Frontend:

```bash
cd frontend && npm run typecheck && npm test && npm run build
```

- [ ] **Step 3: Commit docs**

```bash
git add CLAUDE.md deploy/README.md
git commit -m "docs(audio): document cloud TTS setup"
```

- [ ] **Step 4: Final status**

Run:

```bash
git status --short
```

Expected only unrelated pre-existing untracked files remain (`test2.html`, older specs). Report commits and verification output.

---

## Self-Review

- Spec coverage: DB metadata, TTS config, service, routes, scopes, practice read route, word UI, dictation fallback, tests, docs, OpenAPI are covered.
- Placeholder scan: no TBD/TODO placeholders; steps include exact paths and representative code. Some long existing dense Vue files require local adaptation but target functions and UI strings are specified.
- Type consistency: `audio_path/audio_format/audio_voice/audio_generated_at/audio_bytes`, `WordAudioBatchResult`, `sessionItemAudioUrl`, `generateWordAudio`, and `generateMissingWordAudio` names are used consistently.
