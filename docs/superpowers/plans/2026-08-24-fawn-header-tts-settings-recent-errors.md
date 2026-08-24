# 梅花鹿页头 · TTS 设置补齐 · 概览错词卡片 实现计划

> **For agentic workers:** 本仓库用户约定（~/.claude-glm/CLAUDE.md）：子代理只做探索，代码修改与验证一律由主代理执行 → 采用 **inline（executing-plans）** 方式执行本计划。

**Goal:** 落实已批准规格 `docs/superpowers/specs/2026-08-24-fawn-header-tts-settings-recent-errors-design.md` 的三个功能：① 复习表页头按星期显示手绘 SVG 梅花鹿（位置周一→周日从左到右）；② TTS「导入自动生成」开关 + 豆包细调参数进系统设置页；③ 概览页列出最近 5 个错误单词。

**Architecture:** 需求② 扩展现有 `SystemAudioSetting` 单例表（新迁移 0009）与 `audio_runtime_settings()` 覆盖映射，schema/前端加字段，env 仍为默认值；需求③ 在 `reviews.py` 新增 `GET /stats/my-recent-errors`（scopes `practice:read`+`reviews:write`，非 admin 按 actor 隔离，去重限 5）；需求① 纯前端：`worksheetTheme` 加 `weekdayIndex`，新 `FawnIllustration.vue` 内联 SVG 组件挂入 `.ws-hero`。

**Tech Stack:** FastAPI + SQLAlchemy 2 + Alembic（后端）；Vue 3 + Element Plus + vitest/Playwright（前端）。所有 git 写操作用 `rtk proxy git …` + `dangerouslyDisableSandbox`。

**门禁命令：**
- 后端：`cd backend && .venv/bin/ruff check app tests && .venv/bin/pytest -q`（本机无 3.10+，用 dev-lan 容器跑：见 CLAUDE.md `./dev-lan.sh backend` 后 `docker exec myword-lan-backend bash -lc 'TRUSTED_HOSTS=localhost,127.0.0.1,testserver PUBLIC_BASE_URL=http://localhost:8000 CORS_ORIGINS=http://localhost:8000 pytest -q'`；若容器不可用则记录阻塞项，以 CI 为准）
- 契约：`.venv/bin/python scripts/export_openapi.py`（容器内同路径）
- 前端：`cd frontend && npm run typecheck && npm test && npm run build`

---

## Task 1: 迁移 0009 + ORM 列（需求② 数据层）

**Files:**
- Create: `backend/migrations/versions/0009_audio_runtime_tuning.py`
- Modify: `backend/migrations/released-migrations.sha256.json`
- Modify: `backend/app/models/entities.py`（SystemAudioSetting，约 L227-237）
- Modify: `backend/tests/test_operations.py`（版本号断言 + 新升级测试）

- [ ] **Step 1: 先写失败测试**——`test_operations.py` 中 `test_real_alembic_upgrade_creates_current_consistent_schema` 的 `== "0008"` 改 `"0009"`；`test_alembic_upgrades_released_revision_0006_to_current` 末段 `"0008"` 改 `"0009"`；`test_health_readiness_requires_current_migration` 里 `INSERT INTO alembic_version VALUES ('0008')` 改 `'0009'`。新增：

```python
def test_alembic_upgrades_released_revision_0008_to_0009(tmp_path):
    database = tmp_path / "released-0008.db"
    backend = Path(__file__).resolve().parents[1]
    environment = {
        **os.environ,
        "DATABASE_URL": f"sqlite:///{database}",
        "API_TOKEN_PEPPER": "migration-test-pepper-at-least-16",
    }
    released = _run_alembic(backend, environment, "upgrade", "0008")
    assert released.returncode == 0, released.stderr
    result = _run_alembic(backend, environment, "upgrade", "head")
    assert result.returncode == 0, result.stderr
    with sqlite3.connect(database) as db:
        assert db.execute("SELECT version_num FROM alembic_version").fetchone()[0] == "0009"
        columns = {row[1] for row in db.execute("PRAGMA table_info(system_audio_settings)").fetchall()}
    assert {
        "auto_generate_on_import",
        "volc_resource_id",
        "volc_speech_rate",
        "volc_loudness_rate",
        "volc_silence_ms",
    } <= columns
```

- [ ] **Step 2: 跑迁移测试确认失败**（无 0009 时 head=0008，断言失败）

- [ ] **Step 3: 写迁移 0009**（模式照抄 0008 的幂等加列）：

```python
"""Persist administrator-managed TTS runtime tuning (import toggle + volc knobs).

Revision ID: 0009
Revises: 0008
"""

from alembic import op
import sqlalchemy as sa


revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = {column["name"] for column in inspector.get_columns("system_audio_settings")}
    columns = {
        "auto_generate_on_import": sa.Boolean(),
        "volc_resource_id": sa.String(length=64),
        "volc_speech_rate": sa.Integer(),
        "volc_loudness_rate": sa.Integer(),
        "volc_silence_ms": sa.Integer(),
    }
    for name, column_type in columns.items():
        if name not in existing:
            op.add_column("system_audio_settings", sa.Column(name, column_type, nullable=True))


def downgrade() -> None:
    for name in (
        "volc_silence_ms",
        "volc_loudness_rate",
        "volc_speech_rate",
        "volc_resource_id",
        "auto_generate_on_import",
    ):
        op.drop_column("system_audio_settings", name)
```

- [ ] **Step 4: entities.py `SystemAudioSetting`** 在 `volc_voice` 列后追加（确认文件头已 import `Boolean`，没有则补）：

```python
    # Runtime tuning managed alongside the provider overrides.  Null keeps the
    # corresponding environment/default behaviour.
    auto_generate_on_import: Mapped[bool | None] = mapped_column(Boolean)
    volc_resource_id: Mapped[str | None] = mapped_column(String(64))
    volc_speech_rate: Mapped[int | None] = mapped_column(Integer)
    volc_loudness_rate: Mapped[int | None] = mapped_column(Integer)
    volc_silence_ms: Mapped[int | None] = mapped_column(Integer)
```

- [ ] **Step 5: 更新 manifest**：`sha256sum backend/migrations/versions/0009_audio_runtime_tuning.py`，把哈希加进 `released-migrations.sha256.json`。

- [ ] **Step 6: 跑迁移测试通过**（`pytest tests/test_operations.py tests/test_migration_history.py -q`）

- [ ] **Step 7: Commit** `rtk proxy git commit -m "feat: 音频运行时调优字段迁移 0009"`

## Task 2: 服务层覆盖 + schema + GET/PUT 扩展（需求② 后端）

**Files:**
- Modify: `backend/app/schemas/contracts.py:132-150`
- Modify: `backend/app/services/system_settings.py`
- Modify: `backend/app/api/system.py:118-155`（仅传参一处）
- Test: `backend/tests/test_audio_runtime_settings.py`（新建）

- [ ] **Step 1: 新测试文件**（先失败）：

```python
from __future__ import annotations

from app.services.system_settings import audio_runtime_settings


def _put(client, version, **overrides):
    payload = {"default_provider": "mimo", "expected_version": version}
    payload.update(overrides)
    return client.put("/api/v1/system/audio-settings", json=payload)


def test_put_persists_volc_tuning_and_import_toggle(client, db_session):
    first = _put(client, 1, volc={"resource_id": "seed-tts-2.0", "speech_rate": -20, "loudness_rate": 30, "silence_ms": 800}, auto_generate_on_import=False)
    assert first.status_code == 200, first.text
    data = first.json()["data"]
    assert data["auto_generate_on_import"] is False
    assert data["volc_tuning"] == {"resource_id": "seed-tts-2.0", "speech_rate": -20, "loudness_rate": 30, "silence_ms": 800}
    assert audio_runtime_settings(db_session).tts_auto_generate_on_import is False
    assert audio_runtime_settings(db_session).volc_speech_rate == -20


def test_volc_tuning_null_clears_override_back_to_env(client, db_session):
    _put(client, 1, volc={"speech_rate": -20}, auto_generate_on_import=True)
    cleared = _put(client, 2, volc={"speech_rate": None})
    assert cleared.status_code == 200, cleared.text
    settings = audio_runtime_settings(db_session)
    assert settings.volc_speech_rate == -10  # env 默认
    assert settings.tts_auto_generate_on_import is True  # 未提交则保持


def test_volc_tuning_bounds_rejected(client):
    assert _put(client, 1, volc={"speech_rate": 500}).status_code == 422
    assert _put(client, 1, volc={"silence_ms": -1}).status_code == 422
    assert _put(client, 1, volc={"resource_id": "x" * 65}).status_code == 422


def test_get_reports_effective_tuning(client, db_session):
    response = client.get("/api/v1/system/audio-settings")
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["auto_generate_on_import"] is True  # env 默认 true
    assert data["volc_tuning"]["resource_id"] == "seed-tts-2.0"
    assert data["volc_tuning"]["silence_ms"] == 500
```

- [ ] **Step 2: 跑测试确认失败**（422 on unknown fields / 缺 volc_tuning）

- [ ] **Step 3: contracts.py**——`AudioProviderSettingsUpdate` 追加 4 个可选字段并把 `resource_id` 加进 trim 校验器：

```python
class AudioProviderSettingsUpdate(StrictModel):
    base_url: str | None = Field(default=None, max_length=500)
    api_key: str | None = Field(default=None, max_length=1000)
    model: str | None = Field(default=None, max_length=200)
    voice: str | None = Field(default=None, max_length=200)
    # Volc-only tuning knobs; mimo ignores them.
    resource_id: str | None = Field(default=None, max_length=64)
    speech_rate: int | None = Field(default=None, ge=-50, le=100)
    loudness_rate: int | None = Field(default=None, ge=0, le=100)
    silence_ms: int | None = Field(default=None, ge=0, le=5000)

    @field_validator("base_url", "api_key", "model", "voice", "resource_id")
    @classmethod
    def trim_values(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip() or None


class SystemAudioSettingsUpdate(StrictModel):
    default_provider: AudioProvider
    expected_version: int = Field(gt=0)
    mimo: AudioProviderSettingsUpdate | None = None
    volc: AudioProviderSettingsUpdate | None = None
    auto_generate_on_import: bool | None = None
```

- [ ] **Step 4: system_settings.py**
  - `audio_runtime_settings` 的 `values` 字典追加：

```python
            "volc_resource_id": setting.volc_resource_id or settings.volc_resource_id,
            "volc_speech_rate": (
                setting.volc_speech_rate
                if setting.volc_speech_rate is not None
                else settings.volc_speech_rate
            ),
            "volc_loudness_rate": (
                setting.volc_loudness_rate
                if setting.volc_loudness_rate is not None
                else settings.volc_loudness_rate
            ),
            "volc_silence_ms": (
                setting.volc_silence_ms
                if setting.volc_silence_ms is not None
                else settings.volc_silence_ms
            ),
            "tts_auto_generate_on_import": (
                setting.auto_generate_on_import
                if setting.auto_generate_on_import is not None
                else settings.tts_auto_generate_on_import
            ),
```

  - `audio_settings_data` 返回值追加两个非密字段（catalog 之后）：

```python
    runtime = audio_runtime_settings(db)
    return {
        **catalog,
        "default_provider": catalog["current"],
        "auto_generate_on_import": runtime.tts_auto_generate_on_import,
        "volc_tuning": {
            "resource_id": runtime.volc_resource_id,
            "speech_rate": runtime.volc_speech_rate,
            "loudness_rate": runtime.volc_loudness_rate,
            "silence_ms": runtime.volc_silence_ms,
        },
        "version": setting.version if setting is not None else 1,
        ...
```

  - 新增清洗函数（数值型：显式 None = 清除覆盖；字符串：空=清除）：

```python
def _volc_tuning_values(payload: dict[str, object] | None) -> dict[str, object]:
    """Cleanse the volc-only tuning knobs; explicit None clears the override."""
    if not payload:
        return {}
    result: dict[str, object] = {}
    for key in ("resource_id", "speech_rate", "loudness_rate", "silence_ms"):
        if key not in payload:
            continue
        value = payload[key]
        if key == "resource_id":
            cleaned = str(value).strip() if value is not None else ""
            result[key] = cleaned or None
        else:
            result[key] = value
    return result
```

  - `update_audio_settings` 签名加 `auto_generate_on_import: bool | None = None`；在 provider 循环后追加：

```python
    if auto_generate_on_import is not None:
        setting.auto_generate_on_import = auto_generate_on_import
    for field, value in _volc_tuning_values((provider_configs or {}).get("volc")).items():
        setattr(setting, f"volc_{field}", value)
```

- [ ] **Step 5: api/system.py** `save_audio_settings` 调用处加一个参数：`auto_generate_on_import=payload.auto_generate_on_import,`

- [ ] **Step 6: 跑 Task2 测试 + 既有 `tests/test_system_backup.py tests/test_word_audio.py` 全通过**

- [ ] **Step 7: 重导出契约**（容器内或 venv）`python scripts/export_openapi.py`，`rtk proxy git diff --stat backend/contracts/openapi.yaml` 确认有预期新增字段

- [ ] **Step 8: Commit** `feat: TTS 导入开关与豆包细调参数支持运行时配置`

## Task 3: 系统页 UI（需求② 前端）

**Files:**
- Modify: `frontend/src/types/domain.ts:111-116`
- Modify: `frontend/src/api/system.ts:16-33`
- Modify: `frontend/src/views/SystemView.vue`（script L81-130 + 模板 L430-462）

- [ ] **Step 1: domain.ts** `SystemAudioSettings` 追加：

```ts
export interface VolcTuning { resource_id: string; speech_rate: number; loudness_rate: number; silence_ms: number }
export interface SystemAudioSettings extends AudioProvidersInfo {
  default_provider: AudioProvider
  auto_generate_on_import: boolean
  volc_tuning: VolcTuning
  version: number
  updated_at: string | null
  updated_by: string | null
}
```

- [ ] **Step 2: api/system.ts**——payload 接口与保存函数：

```ts
export interface AudioProviderSettingsPayload {
  base_url: string
  api_key: string
  model: string
  voice: string
  resource_id?: string | null
  speech_rate?: number | null
  loudness_rate?: number | null
  silence_ms?: number | null
}

export async function saveAudioSettings(
  defaultProvider: AudioProvider,
  expectedVersion: number,
  providers: Partial<Record<AudioProvider, AudioProviderSettingsPayload>> = {},
  autoGenerateOnImport?: boolean,
) {
  return unwrap((await apiClient.put<ApiEnvelope<SystemAudioSettings>>('/system/audio-settings', {
    default_provider: defaultProvider,
    expected_version: expectedVersion,
    auto_generate_on_import: autoGenerateOnImport ?? null,
    ...providers,
  })).data)
}
```

- [ ] **Step 3: SystemView.vue**——script：`audioDraft.volc` 增 `resource_id: ''` 与 `speech_rate/loudness_rate/silence_ms: null`；新增 `const autoImportDraft = ref(false)`；`loadAudioSettings`/`persistAudioSettings` 保存成功回调里同步：`autoImportDraft.value = settings.auto_generate_on_import`、volc tuning 回填 draft（数字空值→null）。`persistAudioSettings` 调 `saveAudioSettings(defaultAudioProvider.value, version, {mimo:{...audioDraft.mimo}, volc:{...audioDraft.volc}}, autoImportDraft.value)`。模板（volc 连接设置块之后）：

```html
<label class="audio-model-field">
  <span><strong>导入单词时自动生成语音</strong><small>关闭后，词库导入不再自动排队生成发音</small></span>
  <span class="audio-model-control">
    <el-switch v-model="autoImportDraft" aria-label="导入单词时自动生成语音" />
  </span>
</label>
```
volc provider 的 `.audio-provider-fields` 后加：

```html
<div v-if="provider.id === 'volc'" class="audio-provider-fields volc-tuning">
  <el-input v-model="audioDraft.volc.resource_id" aria-label="豆包资源ID" placeholder="资源 ID（默认 seed-tts-2.0）" />
  <el-input-number v-model="audioDraft.volc.speech_rate" :min="-50" :max="100" aria-label="豆包语速" placeholder="语速" />
  <el-input-number v-model="audioDraft.volc.loudness_rate" :min="0" :max="100" aria-label="豆包音量" placeholder="音量" />
  <el-input-number v-model="audioDraft.volc.silence_ms" :min="0" :max="5000" :step="100" aria-label="豆包尾部停顿" placeholder="尾部停顿 ms" />
</div>
<p v-if="provider.id === 'volc'" class="muted audio-tuning-hint">语速 &lt;0 更平稳；音量 &gt;0 更有力；停顿留白毫秒。清空数字 = 恢复环境变量默认值。</p>
```
保存按钮文案改「保存设置」。

- [ ] **Step 4: `npm run typecheck && npm test && npm run build` 全绿**

- [ ] **Step 5: Commit** `feat: 系统页可视配置导入语音开关与豆包细调`

## Task 4: 最近错误单词接口（需求③ 后端）

**Files:**
- Modify: `backend/app/api/reviews.py`（imports + 新路由，放 `own_stats_contributions` 后）
- Modify: `backend/app/main.py` `REQUIRED_SCOPES`
- Test: `backend/tests/test_recent_errors.py`（新建）

- [ ] **Step 1: 新测试**（模板取自 `test_today_reviews.py`：`seed_credential`/`create_word` 来自 conftest）：

```python
from __future__ import annotations

from app.models import ReviewLog
from conftest import create_word, seed_credential


def _login(client, username: str, password: str) -> None:
    response = client.post("/api/v1/auth/login", json={"username": username, "password": password})
    assert response.status_code == 200, response.text


def _seed_unknown(db_session, word_id: int, actor_id: str, reviewed_at: str, event: str) -> None:
    db_session.add(
        ReviewLog(
            word_id=word_id,
            status="unknown",
            source="quick_review",
            actor_type="web_user",
            actor_id=actor_id,
            client_event_id=event,
            reviewed_at=reviewed_at,
        )
    )
    db_session.commit()


def test_recent_errors_isolated_deduped_and_capped(client, db_session, login_mode):
    seed_credential(db_session, "admin", "supersecret")
    seed_credential(db_session, "student", "student1", role="student")
    words = [create_word(client, {"en_word": f"w{index}", "cn_meaning": f"词{index}", "tags": []}) for index in range(6)]

    _seed_unknown(db_session, words[0]["id"], "student", "2026-08-20T01:00:00Z", "s-1a")
    _seed_unknown(db_session, words[0]["id"], "student", "2026-08-21T01:00:00Z", "s-1b")  # 同词最新一条生效
    _seed_unknown(db_session, words[1]["id"], "student", "2026-08-19T01:00:00Z", "s-2")
    _login(client, "student", "student1")
    for index in range(2, 6):
        _seed_unknown(db_session, words[index]["id"], "student", f"2026-08-1{index}:00:00Z", f"s-{index}")
    data = client.get("/api/v1/stats/my-recent-errors").json()["data"]
    ids = [item["word_id"] for item in data["items"]]
    assert len(ids) == 5  # 上限 5
    assert len(set(ids)) == 5  # 去重
    assert ids[0] == words[5]["id"]  # 时间倒序
    assert ids[1] == words[4]["id"]
    assert data["items"][0]["en_word"] == "w5"
    assert data["items"][0]["cn_meaning"] == "词5"
    assert data["items"][0]["reviewed_at"] == "2026-08-15:00:00Z"

    seed_credential(db_session, "student2", "student2", role="student")
    client.post("/api/v1/auth/logout")
    _login(client, "student2", "student2")
    assert client.get("/api/v1/stats/my-recent-errors").json()["data"]["items"] == []

    client.post("/api/v1/auth/logout")
    _login(client, "admin", "supersecret")
    admin_items = client.get("/api/v1/stats/my-recent-errors").json()["data"]["items"]
    assert {item["word_id"] for item in admin_items} == {word["id"] for word in words}

    operation = client.get("/openapi.json").json()["paths"]["/api/v1/stats/my-recent-errors"]["get"]
    assert operation["x-required-scopes"] == ["practice:read", "reviews:write"]
```

注意：已知(known)记录不出现——在 student 场景追加一条 `_seed` 为 `status="known"` 的对照（event 唯一），断言其 word 不在 items。

- [ ] **Step 2: 跑测试确认 404 失败**

- [ ] **Step 3: reviews.py**——import 区加 `Word`；`own_stats_contributions` 之后加路由：

```python
@router.get("/stats/my-recent-errors")
def own_recent_error_words(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    actor: Annotated[Actor, Depends(require_scopes("practice:read", "reviews:write"))],
):
    """Latest distinct wrongly-recalled words; admin sees everyone's."""
    filters: list[object] = [ReviewLog.status == "unknown"]
    if actor.role != "admin":
        filters.extend(_own_review_filters(actor))
    rows = db.execute(
        select(ReviewLog, Word)
        .join(Word, Word.id == ReviewLog.word_id)
        .where(*filters)
        .order_by(ReviewLog.reviewed_at.desc(), ReviewLog.id.desc())
        .limit(200)
    ).all()
    items: list[dict[str, object]] = []
    seen: set[int] = set()
    for log, word in rows:
        if log.word_id in seen:
            continue
        seen.add(log.word_id)
        items.append(
            {
                "word_id": log.word_id,
                "en_word": word.en_word,
                "phonetic": word.phonetic,
                "cn_meaning": word.cn_meaning,
                "reviewed_at": log.reviewed_at,
            }
        )
        if len(items) == 5:
            break
    return envelope(request, {"items": items})
```

- [ ] **Step 4: main.py `REQUIRED_SCOPES`** 加：`("GET", "/api/v1/stats/my-recent-errors"): ["practice:read", "reviews:write"],`（放 my-contributions 风格的 stats 条目附近）

- [ ] **Step 5: 测试通过 + `python scripts/export_openapi.py` 重导出契约**

- [ ] **Step 6: Commit** `feat: 学员概览最近错误单词接口`

## Task 5: 概览页错词卡片（需求③ 前端）

**Files:**
- Modify: `frontend/src/types/domain.ts`（新增类型）
- Modify: `frontend/src/api/stats.ts`
- Modify: `frontend/src/views/DashboardView.vue`
- Modify: `frontend/tests/e2e/stage3.spec.ts`（installApi mock + 概览断言）

- [ ] **Step 1: domain.ts**：

```ts
export interface RecentErrorWord { word_id: number; en_word: string; phonetic: string | null; cn_meaning: string; reviewed_at: string }
export interface RecentErrorWords { items: RecentErrorWord[] }
```

- [ ] **Step 2: stats.ts**：

```ts
export async function getRecentErrors(signal?: AbortSignal) { return unwrap((await apiClient.get<ApiEnvelope<RecentErrorWords>>('/stats/my-recent-errors', { signal })).data) }
```

- [ ] **Step 3: DashboardView.vue**——state 类型加 `recentErrors: RecentErrorWords`；两个分支的 `Promise.all` 都加 `getRecentErrors(signal)`；模板 `</div>`（dashboard-grid 结束）后加：

```html
<article class="panel recent-errors">
  <div class="section-title"><div><p class="eyebrow">RECENT ERRORS</p><h2>最近错误单词</h2></div></div>
  <p class="muted">最近标记为「不认识」的单词（同词只记一次），复习时优先照顾它们。</p>
  <ul v-if="state.data.value.recentErrors.items.length" class="recent-error-list">
    <li v-for="item in state.data.value.recentErrors.items" :key="item.word_id">
      <strong class="re-word">{{ item.en_word }}</strong>
      <span class="re-phonetic">{{ item.phonetic ? formatPhonetic(item.phonetic) : '' }}</span>
      <span class="re-meaning">{{ item.cn_meaning }}</span>
      <small class="re-time">{{ new Date(item.reviewed_at).toLocaleDateString('zh-CN') }}</small>
    </li>
  </ul>
  <p v-else class="muted">最近没有错误记录，继续保持。</p>
</article>
```
（import `formatPhonetic`。）scoped 样式：

```css
.recent-error-list{list-style:none;margin:12px 0 0;padding:0;display:grid;gap:8px}
.recent-error-list li{display:flex;align-items:baseline;gap:12px;padding:9px 14px;border:1px solid var(--line);border-radius:10px;background:#fff}
.re-word{font-family:Georgia,serif;font-size:1.05rem;color:#17243a}
.re-phonetic{color:#4a6075;font-size:.8rem}
.re-meaning{color:#33415c;font-size:.85rem}
.re-time{margin-left:auto;color:var(--muted);font-size:.72rem;white-space:nowrap}
@media(max-width:639px){.recent-error-list li{flex-wrap:wrap;gap:4px 10px}.re-time{margin-left:0;width:100%}}
```

- [ ] **Step 4: stage3.spec.ts installApi** 加 mock（在 stats/contributions 旁）：

```ts
if (path === '/api/v1/stats/my-recent-errors') return route.fulfill({ json: envelope({ items: [{ word_id: 1, en_word: 'serendipity', phonetic: '/ˌserənˈdɪpəti/', cn_meaning: '意外发现美好事物的能力', reviewed_at: '2026-07-20T02:00:00Z' }] }) })
```
概览用例（"responsive overview"所在 test）补断言：`await expect(page.locator('.recent-errors .re-word').first()).toHaveText('serendipity')`。

- [ ] **Step 5: typecheck + vitest + build 全绿；Commit** `feat: 概览页展示最近错误单词`

## Task 6: 梅花鹿页头（需求① 前端）

**Files:**
- Modify: `frontend/src/utils/worksheetTheme.ts`
- Create: `frontend/src/components/FawnIllustration.vue`
- Modify: `frontend/src/components/PracticeWorksheet.vue`
- Modify: `frontend/src/styles/print.css`
- Test: `frontend/tests/unit/worksheetTheme.spec.ts`、`frontend/tests/unit/practiceWorksheet.spec.ts`

- [ ] **Step 1: worksheetTheme**——接口加 `weekdayIndex: number`；VIVID 七项分别加 `weekdayIndex`（sun:7, mon:1, tue:2, wed:3, thu:4, fri:5, sat:6）。spec 加断言：`expect(worksheetTheme('2026-07-20T00:00:00Z').weekdayIndex).toBe(1)`、`…('2026-07-26T00:00:00Z').weekdayIndex).toBe(7)`。

- [ ] **Step 2: 新建 FawnIllustration.vue**（共享躯干 + 7 姿势，姿势差异集中在 transform 表与少量覆盖元素；`data-variant` 供测试）：

```vue
<script setup lang="ts">
// Hand-drawn Bambi-style fawn, one pose per weekday.  Same palette as the
// weekday theme (accents pick up --ws-accent) so it prints in color and
// still reads as a silhouette in grayscale.
type Variant = 'sun' | 'mon' | 'tue' | 'wed' | 'thu' | 'fri' | 'sat'
const props = withDefaults(defineProps<{ variant?: string; width?: number }>(), { variant: 'mon', width: 84 })

interface Pose {
  fawn?: string   // whole-body transform
  head?: string   // head-group transform
  closed?: boolean // eyes drawn as sleeping arcs
  extra?: 'sniff' | 'prance' | 'stretch' | 'rest'
}
const POSES: Record<Variant, Pose> = {
  mon: {},
  tue: { head: 'rotate(-12 36 36)' },
  wed: { head: 'translate(2 13) rotate(10 36 36)', extra: 'sniff' },
  thu: { head: 'translate(26 -3) rotate(30 36 36)' },
  fri: { fawn: 'rotate(-6 58 56)', extra: 'prance' },
  sat: { fawn: 'rotate(9 62 58)', head: 'translate(3 10) rotate(-4 36 36)', extra: 'stretch' },
  sun: { head: 'translate(14 26) rotate(24 36 36)', closed: true, extra: 'rest' },
}
const key = (props.variant in POSES ? props.variant : 'mon') as Variant
const pose = POSES[key]
</script>

<template>
  <svg class="fawn-illustration" :data-variant="key" :width="width" :height="Math.round(width * 0.75)" viewBox="0 0 120 90" role="img" aria-label="星期小鹿插图">
    <!-- shared enchanted-forest backdrop -->
    <ellipse cx="62" cy="60" rx="54" ry="30" fill="#fdf3dd" opacity=".55" />
    <path d="M20 12 L44 44 M34 8 L52 40 M50 10 L62 38" stroke="#f7d9a0" stroke-width="3" stroke-linecap="round" opacity=".45" />
    <ellipse cx="60" cy="83" rx="42" ry="6" fill="#cfe3bd" opacity=".65" />
    <g stroke="#9db98a" stroke-width="1.4" stroke-linecap="round" opacity=".8">
      <path d="M18 82 L16 76 M21 82 L22 75 M98 83 L96 77 M101 83 L103 76" />
    </g>
    <g><!-- wildflowers -->
      <circle cx="14" cy="77" r="2.2" fill="#f9c6d0" /><circle cx="18" cy="79" r="2.2" fill="#f9c6d0" /><circle cx="16" cy="81.5" r="2.2" fill="#f9c6d0" /><circle cx="12" cy="81" r="2.2" fill="#f9c6d0" /><circle cx="15.5" cy="79.5" r="1.7" fill="#f3c53d" />
      <circle cx="104" cy="79" r="2" fill="#fde8c0" /><circle cx="108" cy="80.5" r="2" fill="#fde8c0" /><circle cx="106" cy="83" r="2" fill="#fde8c0" /><circle cx="106" cy="80.4" r="1.5" fill="var(--ws-accent, #fbbf24)" />
    </g>
    <g v-if="pose.extra === 'sniff'" class="sniff-flower">
      <circle cx="26" cy="60" r="3" fill="#f9c6d0" /><circle cx="21" cy="62" r="2.6" fill="#f9c6d0" /><circle cx="31" cy="62" r="2.6" fill="#f9c6d0" /><circle cx="26" cy="64" r="2.6" fill="#f9c6d0" /><circle cx="26" cy="61.8" r="2" fill="#f3c53d" />
    </g>
    <g v-if="pose.extra === 'prance'" stroke="#f7d9a0" stroke-width="2" stroke-linecap="round" opacity=".7">
      <path d="M86 44 q6 -4 5 -11 M92 52 q7 -2 8 -9" fill="none" />
    </g>

    <g class="fawn" :transform="pose.fawn || ''">
      <!-- spindly legs (lying pose folds them) -->
      <g v-if="pose.extra !== 'rest'" stroke="#b5793f" stroke-width="2.6" stroke-linecap="round" fill="none">
        <path d="M44 64 L41 81 M50 65 L49 81 M68 64 L72 81 M74 62 L78 80" />
      </g>
      <g v-else stroke="#b5793f" stroke-width="2.6" stroke-linecap="round" fill="none">
        <path d="M40 68 L58 68 M74 66 L90 66" />
      </g>
      <!-- body / belly / chest / tail -->
      <ellipse cx="58" cy="57" rx="20" ry="11.5" fill="#d9a066" />
      <ellipse cx="58" cy="61" rx="12.5" ry="6" fill="#f6e7cd" />
      <ellipse cx="43" cy="57" rx="4.5" ry="6" fill="#f6e7cd" />
      <circle cx="77" cy="51" r="3.4" fill="#fdf6ea" />
      <!-- white dappled spots -->
      <g fill="#fdf6ea">
        <circle cx="52" cy="51" r="2" /><circle cx="59" cy="49" r="1.7" /><circle cx="66" cy="51.5" r="1.9" /><circle cx="55" cy="54.5" r="1.4" /><circle cx="62" cy="55" r="1.5" />
      </g>
      <!-- head group -->
      <g :transform="pose.head || ''">
        <path d="M30 29 C25 21 19 19 16.5 22 C14.5 25 18 30 25 32 Z" fill="#d9a066" />
        <path d="M27 28.4 C24 24 20.5 22.6 19 24 C17.8 25.4 20 28.6 24.6 30 Z" fill="#43301c" />
        <path d="M40 27 C44 19 50 17.5 52.5 20.5 C54.3 23.4 50.8 28.8 44 31 Z" fill="#d9a066" />
        <path d="M42.8 26.4 C45.8 21.6 49.3 20.4 50.7 21.9 C51.8 23.4 49.4 26.9 45 28.4 Z" fill="#43301c" />
        <circle cx="36" cy="37" r="9.6" fill="#d9a066" />
        <ellipse cx="29.5" cy="40" rx="4.8" ry="3.6" fill="#f6e7cd" />
        <circle cx="26.6" cy="39" r="1.5" fill="#43301c" />
        <path d="M27.5 42.2 q2 1.8 4 0.4" fill="none" stroke="#43301c" stroke-width="1.1" stroke-linecap="round" />
        <g v-if="!pose.closed">
          <circle cx="33" cy="36" r="2.3" fill="#3d2817" /><circle cx="33.8" cy="35.2" r="0.8" fill="#fff" />
          <circle cx="40" cy="36.4" r="2.3" fill="#3d2817" /><circle cx="40.8" cy="35.6" r="0.8" fill="#fff" />
        </g>
        <g v-else stroke="#3d2817" stroke-width="1.5" stroke-linecap="round" fill="none">
          <path d="M31.4 36.2 q1.6 1.6 3.2 0 M38.4 36.6 q1.6 1.6 3.2 0" />
        </g>
        <ellipse cx="31" cy="41.6" rx="1.9" ry="1.1" fill="#f2b8a0" opacity=".65" />
      </g>
      <!-- stretch pose: front legs reach forward low -->
      <g v-if="pose.extra === 'stretch'" stroke="#b5793f" stroke-width="2.6" stroke-linecap="round" fill="none">
        <path d="M42 66 L28 79 M48 67 L36 81" />
      </g>
    </g>
  </svg>
</template>

<style scoped>
.fawn-illustration { display: block }
</style>
```

- [ ] **Step 3: PracticeWorksheet.vue**——import `FawnIllustration`；hero 里加（标题与日期卡之间）：

```html
<FawnIllustration class="ws-fawn" :variant="theme.icon" :style="{ left: fawnLeft }" />
```
script 加：

```ts
const fawnLeft = computed(() => `calc(${(22 + (theme.value.weekdayIndex - 1) * (52 / 6)).toFixed(2)}% )`)
```
样式：`.ws-hero` 加 `position:relative`；新增：

```css
.ws-fawn{position:absolute;bottom:2px;width:84px;z-index:1;pointer-events:none;opacity:.96;filter:drop-shadow(0 2px 3px rgba(0,0,0,.18))}
.ws-hero-title,.ws-date-card{position:relative;z-index:2}
```
`@media(max-width:760px)` 内加 `.ws-fawn{width:60px;opacity:.85}`。

- [ ] **Step 4: print.css**（@media print 内，ws-date-card 规则旁）：

```css
.ws-fawn { width: 24mm !important; bottom: 1.2mm !important; }
```

- [ ] **Step 5: 单测**——`practiceWorksheet.spec.ts` 追加：

```ts
it('renders exactly one fawn whose header position slides with the weekday', () => {
  const monday = mount(PracticeWorksheet, { props: { session, answer: false, mode: 'en-to-cn' } }) // 2026-07-20 周一
  expect(monday.findAll('.ws-fawn')).toHaveLength(1)
  expect(monday.get('.ws-fawn').attributes('style')).toContain('left: 22%')
  expect(monday.get('.ws-fawn svg').attributes('data-variant')).toBe('mon')

  const thursday = mount(PracticeWorksheet, { props: { session: { ...session, generated_at: '2026-07-23T00:00:00Z' }, answer: false, mode: 'en-to-cn' } })
  expect(thursday.get('.ws-fawn').attributes('style')).toContain('left: 48%')

  const sunday = mount(PracticeWorksheet, { props: { session: { ...session, generated_at: '2026-07-26T00:00:00Z' }, answer: false, mode: 'en-to-cn' } })
  expect(sunday.get('.ws-fawn').attributes('style')).toContain('left: 74%')
  expect(sunday.get('.ws-fawn svg').attributes('data-variant')).toBe('sun')
})
```
（若 left 计算产生的字符串带尾随空格导致 `toContain('left: 22%')` 失配，改为匹配 `left: 22.00%` 实际输出再断言——以实现为准，先跑再修断言格式。）

- [ ] **Step 6: typecheck + vitest + build 全绿；Commit** `feat: 复习表页头按星期展示梅花鹿插图`

## Task 7: 总门禁 + 推送 + CI 验证

- [ ] **Step 1: 后端全量**：容器内 `ruff check app tests && pytest -q`；`python scripts/export_openapi.py` 已在 Task2/4 执行过，最后 `rtk proxy git status` 确认无遗漏
- [ ] **Step 2: 前端全量**：`npm run typecheck && npm test && npm run build`
- [ ] **Step 3: 更新 CLAUDE.md**——「Cloud TTS audio」一节补一句：TTS 自动导入开关与豆包细调（resource id/语速/音量/停顿）由 `/system` 运行时配置覆盖（`SystemAudioSetting`，null 回落 env）
- [ ] **Step 4: Commit 文档**，然后 `./scripts/push-and-monitor-actions.sh` 推送并等待该 commit 的 `ci.yml` 通过（绿勾）；失败则修复再推
- [ ] **Step 5: 汇报**：三个提交 + CI 结论 + NAS 部署提醒（Portainer 手动 Pull 对应 `sha-<short>` 标签）

---

## Self-Review 记录

- 规格覆盖：鹿图（Task6）／TTS 五字段+迁移+UI（Task1-3）／错词接口+卡片（Task4-5）／交付验证（Task7）——全覆盖；范围外（recitation PDF 加鹿、错词条数可切换）不做。
- 类型一致性：`volc_tuning` 键名前后端一致；`auto_generate_on_import` 全链路同名；`weekdayIndex` 由 `worksheetTheme` 单点产出。
- 已知风险：Playwright 本地不跑（CI 亦不跑 e2e，仅本地可选）；`login_mode` fixture 需存在（test_today_reviews 已在用，安全）。
