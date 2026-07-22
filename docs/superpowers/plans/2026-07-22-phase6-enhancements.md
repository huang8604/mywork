# 阶段六增强批次 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 落地 7 项增强:在线复习「下一题」UX + 学员只读汇总、释义缩到 10-16 字 + AI 重译、txt 导入选词、复习表/md/pdf 排版、API 令牌管理 UI、SQLite 全量备份。

**Architecture:** 四层分层不变(routes→services→models→schemas)。`/api/v1/api-clients` 与 `/api/v1/system/backup` 走角色门禁(`require_web_admin`,不进 `REQUIRED_SCOPES`,`ALL_SCOPES` 不变)。复习 UX 与排版为前端改动;释义/AI/导入/令牌/备份为后端 + 前端。每组独立可提交。

**Tech Stack:** FastAPI + SQLAlchemy 2 + SQLite(argon2/itsdangerous);Vue 3 + Pinia + Element Plus + vitest + vue-tsc。后端测试 `.venv/bin/pytest`(FastAPI TestClient + per-test SQLite)。

**Spec:** `docs/superpowers/specs/2026-07-22-phase6-enhancements-design.md`

**完成状态（2026-07-22）：** 全部任务已实现并验收。后端迁移 + 全量测试为
`83 passed, 1 skipped`，Ruff 检查通过；前端类型检查、`41` 项单元测试、生产构建与
`60` 项多视口端到端测试通过。
实现期间补齐了所有用户可见位置的 `/音标/` 统一格式。

---

## File Structure

**Backend — create:**
- `backend/app/api/api_clients.py` — `/api/v1/api-clients` CRUD(role-gated)
- `backend/app/api/system.py` — `/api/v1/system/backup` SQLite 下载
- `backend/tests/test_api_clients_admin.py`
- `backend/tests/test_system_backup.py`

**Backend — modify:**
- `backend/app/services/dictionary.py` — `shorten_translations(target=16)` + `enrich_word` AI 兜底
- `backend/app/services/ai_enrich.py` — prompt 上限 16
- `backend/app/services/recitation.py` — `build_recitation_md` 词+音标同格 + 斜杠
- `backend/app/api/words.py` — `/import` 响应加 `resolved[]`
- `backend/app/schemas/contracts.py` — API client 请求 schemas
- `backend/app/main.py` — 注册路由 + OpenAPI 跳过
- `backend/tests/test_dictionary.py`(已存在,扩)、`backend/tests/test_words_import.py`(扩)、`backend/tests/test_recitation.py`(已存在,扩)

**Frontend — create:**
- `frontend/src/utils/formatPhonetic.ts` — `formatPhonetic(p) => p ? \`/${p}/\` : ''`
- `frontend/src/api/apiClients.ts`
- `frontend/src/views/SystemView.vue`
- `frontend/tests/unit/formatPhonetic.spec.ts`
- `frontend/tests/unit/review.spec.ts`(若不存在则新建)

**Frontend — modify:**
- `frontend/src/views/ReviewView.vue` — 锁定 + 下一题 + 末题置灰 + 完成汇总
- `frontend/src/views/DailyGenerateView.vue` — txt 导入面板
- `frontend/src/components/PracticeWorksheet.vue` — 合并列/不画线/例句全显/斜杠
- `frontend/src/styles/print.css` — `.word-cell { white-space: nowrap }`
- `frontend/src/router/index.ts` — `/system` 路由
- `frontend/src/layouts/AppShell.vue` — 侧栏「系统」
- `frontend/src/types/domain.ts` — ApiClient 等类型
- `frontend/src/api/words.ts` — import 响应类型

---

## 约定(所有任务通用)

- 后端测试命令:`cd backend && .venv/bin/pytest tests/<file>::<test> -v`。若主机 venv 不可用,在 `myword-verify` 容器内跑:`TRUSTED_HOSTS=localhost,127.0.0.1,testserver PUBLIC_BASE_URL=http://localhost:8000 CORS_ORIGINS=http://localhost:8000 .venv/bin/pytest -q`。
- 前端命令:`cd frontend && npm test -- <pattern>` / `npm run typecheck` / `npm run build`。
- 每个 `AppError`/路由改动后,最后跑 `cd backend && .venv/bin/python scripts/export_openapi.py` 并 `git diff --exit-code -- contracts/openapi.yaml`。
- 提交信息结尾加 `Co-Authored-By: Claude <noreply@anthropic.com>`。提交只 `git add` 本任务显式列出的文件(工作区还有未提交的登录功能代码,勿误纳入)。

---

## Phase 0 — 共享:音标格式化器

### Task 0.1: `formatPhonetic` 工具 + 测试

**Files:**
- Create: `frontend/src/utils/formatPhonetic.ts`
- Test: `frontend/tests/unit/formatPhonetic.spec.ts`

- [x] **Step 1: 写失败测试**

```ts
// frontend/tests/unit/formatPhonetic.spec.ts
import { describe, expect, it } from 'vitest'
import { formatPhonetic } from '@/utils/formatPhonetic'

describe('formatPhonetic', () => {
  it('wraps a phonetic in slashes', () => {
    expect(formatPhonetic('ˈkæmərə')).toBe('/ˈkæmərə/')
  })
  it('returns empty string for null/empty so cells stay blank', () => {
    expect(formatPhonetic(null)).toBe('')
    expect(formatPhonetic('')).toBe('')
    expect(formatPhonetic(undefined)).toBe('')
  })
  it('trims surrounding whitespace before wrapping', () => {
    expect(formatPhonetic('  /ə/  ')).toBe('//ə///') // see note
  })
})
```

> **Note:** the trim test above is deliberately wrong — replace its expected value with the correct one once you decide trimming. **Decision:** trim the input, and also strip any existing leading/trailing `/` so we never double-wrap. Final expected for `'  /ə/  '` is `'/ə/'`. Write the test with `'/ə/'`.

- [x] **Step 2: 运行测试确认失败**

Run: `cd frontend && npm test -- formatPhonetic`
Expected: FAIL("Cannot find module '@/utils/formatPhonetic'").

- [x] **Step 3: 实现**

```ts
// frontend/src/utils/formatPhonetic.ts
/** Wrap a phonetic in slashes for display; empty input → empty string (blank cell, no slashes). */
export function formatPhonetic(phonetic: string | null | undefined): string {
  if (!phonetic) return ''
  const trimmed = phonetic.trim().replace(/^\/+|\/+$/g, '')
  if (!trimmed) return ''
  return `/${trimmed}/`
}
```

- [x] **Step 4: 运行测试确认通过**

Run: `cd frontend && npm test -- formatPhonetic`
Expected: PASS (3 tests).

- [x] **Step 5: 提交**

```bash
git add frontend/src/utils/formatPhonetic.ts frontend/tests/unit/formatPhonetic.spec.ts
git commit -m "feat: add formatPhonetic util for /phonetic/ display

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Phase A — 在线复习 UX(#1 + #5)

### Task A1: 答题后锁定 + 「下一题」主按钮 + 末题置灰

**Files:**
- Modify: `frontend/src/views/ReviewView.vue`
- Test: `frontend/tests/unit/review.spec.ts`

**行为目标:**
- 未答(`revealed=false`):`ResultSelector` 三按钮可选。
- 已答(`revealed=true`):`ResultSelector` 隐藏,改为显示「已记录:认识/不认识/跳过」徽章 + 主按钮「下一题」(`@click="next"`)。
- 末题(`index === total-1`):主按钮 `disabled`,文案「已完成 ✓」。

- [x] **Step 1: 写失败测试**

```ts
// frontend/tests/unit/review.spec.ts
import { describe, expect, it } from 'vitest'
// Pure helper extracted from ReviewView so the lock/label logic is unit-testable
// without mounting the full async component.
import { nextButtonLabel } from '@/views/ReviewView.vue.helpers'

describe('review next-button label', () => {
  it('shows 下一题 when more cards remain', () => {
    expect(nextButtonLabel({ index: 2, total: 10, revealed: true })).toBe('下一题')
  })
  it('shows 已完成 ✓ and signals disabled on the last card', () => {
    const r = nextButtonLabel({ index: 9, total: 10, revealed: true })
    expect(r.label).toBe('已完成 ✓')
    expect(r.disabled).toBe(true)
  })
})
```

> If extracting a `.helpers.ts` sidecar is awkward, instead implement `nextButtonLabel` as an exported function inside `ReviewView.vue`'s `<script setup>` is NOT importable; therefore put the pure logic in `frontend/src/views/reviewLogic.ts` and import it into ReviewView. Adjust the import path in the test to `@/views/reviewLogic`.

- [x] **Step 2: 运行测试确认失败**

Run: `cd frontend && npm test -- review`
Expected: FAIL(module not found).

- [x] **Step 3: 抽取纯逻辑 `reviewLogic.ts`**

```ts
// frontend/src/views/reviewLogic.ts
export interface NextButtonState { label: string; disabled: boolean }

export function nextButtonLabel(state: { index: number; total: number; revealed: boolean }): string {
  return isLast(state) ? '已完成 ✓' : '下一题'
}

export function nextButtonDisabled(state: { index: number; total: number }): boolean {
  return isLast(state)
}

function isLast(s: { index: number; total: number }): boolean {
  return s.total <= 0 || s.index >= s.total - 1
}
```

> Fix the test to match: it calls `nextButtonLabel(...)` (returns string) and `nextButtonDisabled(...)` for the disabled flag. Update Step 1's second case to:
> ```ts
> expect(nextButtonLabel({ index: 9, total: 10, revealed: true })).toBe('已完成 ✓')
> expect(nextButtonDisabled({ index: 9, total: 10 })).toBe(true)
> ```

- [x] **Step 4: 运行测试确认通过**

Run: `cd frontend && npm test -- reviewLogic`
Expected: PASS.

- [x] **Step 5: 在 `ReviewView.vue` 模板里替换控件区**

Locate the `.review-controls` block (line ~24, the `<ResultSelector .../>` line). Replace the controls content so that:
- when `!revealed`: render `<ResultSelector :disabled="busy" @select="choose" />`;
- when `revealed`: render a locked badge `<span class="locked-status">{{ statusText(result?.status) }}</span>` + `<el-button type="primary" :disabled="nextButtonDisabled({index,total:progress.total})" @click="next">{{ nextButtonLabel({index,total:progress.total,revealed}) }}</el-button>`.

Add `<script setup>` imports:
```ts
import { nextButtonLabel, nextButtonDisabled } from '@/views/reviewLogic'
```
Add a small `statusText` helper in the script:
```ts
function statusText(s: ReviewStatus | undefined | null) {
  return s === 'known' ? '已记录：认识' : s === 'unknown' ? '已记录：不认识' : '已记录：跳过'
}
```
Keep the existing `.review-top` prev/next nav (it already disables on last) — it now complements the new primary button.

- [x] **Step 6: 运行前端 typecheck + test + build**

Run: `cd frontend && npm run typecheck && npm test && npm run build`
Expected: typecheck clean; tests pass; build succeeds.

- [x] **Step 7: 提交**

```bash
git add frontend/src/views/reviewLogic.ts frontend/src/views/ReviewView.vue frontend/tests/unit/review.spec.ts
git commit -m "feat(review): lock answer + primary 下一题 button, disabled on last card

Co-Authored-By: Claude <noreply@anthropic.com>"
```

### Task A2: 完成汇总(#5,只读,无新接口)

**Files:**
- Modify: `frontend/src/views/ReviewView.vue`、`frontend/src/views/reviewLogic.ts`
- Test: `frontend/tests/unit/review.spec.ts`

- [x] **Step 1: 写失败测试(汇总计数)**

```ts
// append to frontend/tests/unit/review.spec.ts
import { summarize } from '@/views/reviewLogic'

describe('review summary', () => {
  it('counts known/unknown/skipped from a results map', () => {
    const results = new Map([
      [1, { status: 'known' } as any],
      [2, { status: 'unknown' } as any],
      [3, { status: 'skipped' } as any],
      [4, { status: 'known' } as any],
    ])
    expect(summarize(results)).toEqual({ known: 2, unknown: 1, skipped: 1, total: 4 })
  })
})
```

- [x] **Step 2: 运行确认失败**

Run: `cd frontend && npm test -- reviewLogic`
Expected: FAIL(`summarize` not exported).

- [x] **Step 3: 实现 `summarize`**

```ts
// append to frontend/src/views/reviewLogic.ts
export interface ReviewSummary { known: number; unknown: number; skipped: number; total: number }

export function summarize(results: Map<number, { status: string }>): ReviewSummary {
  let known = 0, unknown = 0, skipped = 0
  for (const r of results.values()) {
    if (r.status === 'known') known++
    else if (r.status === 'unknown') unknown++
    else if (r.status === 'skipped') skipped++
  }
  return { known, unknown, skipped, total: known + unknown + skipped }
}
```

- [x] **Step 4: 运行确认通过**

Run: `cd frontend && npm test -- reviewLogic`
Expected: PASS.

- [x] **Step 5: 在 `ReviewView.vue` 渲染汇总面板**

In `<script setup>`, import `summarize` and add:
```ts
const summary = computed(() => summarize(results.value as Map<number, { status: string }>))
```
In the template, inside `.review-controls`, after the primary 下一题 button, add (shown only when `finished`):
```html
<section v-if="finished" class="finish-summary panel">
  <h3>本次复习结果</h3>
  <p class="summary-counts">
    认识 {{ summary.known }} · 不认识 {{ summary.unknown }} · 跳过 {{ summary.skipped }}
    （共 {{ summary.total }}）
  </p>
  <ul class="summary-words">
    <li v-for="it in state.data.value?.items" :key="it.item_id">
      <strong>{{ it.word.en_word }}</strong>
      <span class="ph">{{ formatPhonetic(it.word.phonetic) }}</span>
      <span class="cn">{{ it.word.cn_meaning }}</span>
      <span :class="['badge', results.get(it.item_id)?.status]">
        {{ statusText(results.get(it.item_id)?.status) }}
      </span>
    </li>
  </ul>
  <!-- admin only: existing 查看历史 link stays; students have no reviews:read -->
</section>
```
Add imports `import { formatPhonetic } from '@/utils/formatPhonetic'`. Add minimal scoped CSS for `.finish-summary`, `.summary-counts`, `.summary-words li`, `.badge`.

- [x] **Step 6: typecheck + test + build**

Run: `cd frontend && npm run typecheck && npm test && npm run build`
Expected: PASS.

- [x] **Step 7: 提交**

```bash
git add frontend/src/views/reviewLogic.ts frontend/src/views/ReviewView.vue frontend/tests/unit/review.spec.ts
git commit -m "feat(review): read-only finish summary (counts + word list)

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Phase B — 释义缩短/AI + txt 导入(#2 + #3)

### Task B1: `shorten_translations` 目标 16 + 多边界符

**Files:**
- Modify: `backend/app/services/dictionary.py:163-203`
- Test: `backend/tests/test_dictionary.py`

- [x] **Step 1: 写失败测试**

```python
# append to backend/tests/test_dictionary.py
from app.services.dictionary import shorten_translations

def test_shorten_keeps_short_meaning():
    t = [{"pos": "n.", "cn": "相机"}]
    assert shorten_translations(t) == "n. 相机"

def test_shorten_truncates_at_comma_within_16():
    # joined "n. 计算机，电子计算机，计算器" > 16; cut at the ， inside [10,16]
    t = [{"pos": "n.", "cn": "计算机，电子计算机，计算器"}]
    out = shorten_translations(t)
    assert out is not None
    assert len(out) <= 16
    assert out.startswith("n. 计算机")

def test_shorten_returns_none_when_no_boundary_in_window():
    # one long sense, no punctuation in [10,16] → None (AI fallback decides)
    t = [{"pos": "n.", "cn": "超长且无任何标点符号的释义字符串用于测试"}]
    assert shorten_translations(t) is None
```

- [x] **Step 2: 运行确认失败**

Run: `cd backend && .venv/bin/pytest tests/test_dictionary.py -v`
Expected: FAIL(new assertions; current impl returns ≤40 with `…`, not ≤16/None).

- [x] **Step 3: 重写 `shorten_translations`**

Replace the function body in `backend/app/services/dictionary.py`:

```python
_BOUNDARY_CHARS = " ；;,，.。、"

def shorten_translations(
    translations: Any,
    *,
    max_senses: int = 3,
    target: int = 16,
    min_keep: int = 10,
    hard_cap: int = 16,
) -> str | None:
    """Collapse senses into one short Chinese meaning (≤ target chars when possible).

    1) join up to ``max_senses`` cleaned senses with ``；``;
    2) if already ≤ target, return it;
    3) else look for the LAST boundary char (``。；，,; .、``) whose cut yields a
       length in ``[min_keep, target]``; if found, cut there (trim trailing punct);
    4) else return None — the caller decides the AI/hard-truncate fallback.
    """
    if not isinstance(translations, list):
        return None
    items = clean_translation_items(translations, max_senses=max_senses)
    if items:
        parts = [f"{it['pos']} {it['cn']}".strip() for it in items]
    else:
        parts = []
        for entry in translations:
            if not isinstance(entry, dict):
                continue
            meaning = str(entry.get("cn") or "").strip()
            if not meaning:
                continue
            part = str(entry.get("pos") or "").strip()
            parts.append(f"{part} {meaning}".strip())
    text = "；".join(parts)
    if not text:
        return None
    if len(text) <= target:
        return text
    # search the last boundary whose resulting length is within [min_keep, target]
    for i in range(min(target, len(text)), min_keep - 1, -1):
        if text[i - 1] in _BOUNDARY_CHARS:
            return text[: i - 1].strip(_MEANING_PUNCT)
    return None
```

Remove the now-unused `hard_cap` truncation tail (the `cut + "…"` block) — it is replaced by returning `None`. Keep `_MEANING_PUNCT` (already defined line ~122). Drop the `hard_cap` param if no other caller uses it; otherwise keep with default 16. (Verify callers: `_meaning` and the AI branch in `enrich_word` — update them in B2/B3.)

- [x] **Step 4: 运行确认通过**

Run: `cd backend && .venv/bin/pytest tests/test_dictionary.py -v`
Expected: PASS(new tests). If older tests asserted the 40-char `…` behavior, update them to the new contract.

- [x] **Step 5: 提交**

```bash
git add backend/app/services/dictionary.py backend/tests/test_dictionary.py
git commit -m "feat(dictionary): shorten meanings to ≤16 chars with multi-boundary cut

Co-Authored-By: Claude <noreply@anthropic.com>"
```

### Task B2: `enrich_word` AI 兜底(>16 时重译)

**Files:**
- Modify: `backend/app/services/dictionary.py:46-87`(`enrich_word`)
- Test: `backend/tests/test_dictionary.py`

- [x] **Step 1: 写失败测试**

```python
# append to backend/tests/test_dictionary.py
from app.services import dictionary as dict_mod

def test_enrich_uses_ai_when_dictionary_meaning_too_long(monkeypatch):
    # dictionary returns a >16-char meaning with no in-window boundary
    monkeypatch.setattr(dict_mod, "_load_index", lambda p: {
        "supercalifragilistic": {"p0": "/x/", "t": [{"pos": "n.", "cn": "超长且无任何标点符号的释义字符串"}], "s": []}
    })
    monkeypatch.setattr(dict_mod, "get_settings", lambda: _settings_with_ai())
    called = {}
    def fake_ai(word):
        called["word"] = word
        return {"phonetic": None, "cn_meaning": "短释义", "example_sentence": None}
    monkeypatch.setattr(dict_mod, "ai_enrich_word", fake_ai)
    from app.schemas import WordCreate
    enriched, found = dict_mod.enrich_word(WordCreate(en_word="supercalifragilistic"), allow_ai=True)
    assert found is True
    assert enriched.cn_meaning == "短释义"
    assert called["word"] == "supercalifragilistic"

def test_enrich_hard_truncates_when_ai_disabled(monkeypatch):
    monkeypatch.setattr(dict_mod, "_load_index", lambda p: {
        "supercalifragilistic": {"t": [{"pos": "n.", "cn": "超长且无任何标点符号的释义字符串"}]}
    })
    monkeypatch.setattr(dict_mod, "get_settings", lambda: _settings_with_ai(enabled=False))
    from app.schemas import WordCreate
    enriched, _ = dict_mod.enrich_word(WordCreate(en_word="supercalifragilistic"), allow_ai=True)
    assert len(enriched.cn_meaning) <= 16  # ellipsis included in the limit
```

Add a settings stub helper near the test imports:
```python
from types import SimpleNamespace
def _settings_with_ai(enabled=True):
    return SimpleNamespace(
        dictionary_index_path="",
        ai_base_url="https://ai.local" if enabled else "",
        ai_api_key="k" if enabled else "",
    )
```

- [x] **Step 2: 运行确认失败**

Run: `cd backend && .venv/bin/pytest tests/test_dictionary.py -v`
Expected: FAIL(currently AI only triggers on `not cn_meaning`, not on too-long).

- [x] **Step 3: 改 `enrich_word`**

In `backend/app/services/dictionary.py`, after computing `cn_meaning` from the dictionary (line ~56) and BEFORE the existing `if allow_ai and not cn_meaning:` block, insert a too-long branch:

```python
        # Meaning too long and unshorten-able: try AI re-translation first.
        if cn_meaning and len(cn_meaning) > 16 and shorten_translations([{"pos": "", "cn": cn_meaning}]) is None:
            if allow_ai and get_settings().ai_enabled:
                ai = ai_enrich_word(display)
                if ai and ai.get("cn_meaning"):
                    phonetic = phonetic or ai["phonetic"]
                    cn_meaning = ai["cn_meaning"]
                    example_sentence = example_sentence or ai["example_sentence"]
            if cn_meaning and len(cn_meaning) > 16:
                # still too long (AI off/failed): hard-cap to 16 chars total.
                cn_meaning = cn_meaning[:15].rstrip(_MEANING_PUNCT) + "…"
```

Keep the existing `if allow_ai and not cn_meaning:` block (dictionary miss) unchanged. Ensure `get_settings` is imported (it already is, line 10).

- [x] **Step 4: 运行确认通过**

Run: `cd backend && .venv/bin/pytest tests/test_dictionary.py -v`
Expected: PASS.

- [x] **Step 5: 提交**

```bash
git add backend/app/services/dictionary.py backend/tests/test_dictionary.py
git commit -m "feat(dictionary): AI re-translate meanings still >16 chars after shorten

Co-Authored-By: Claude <noreply@anthropic.com>"
```

### Task B3: AI prompt 上限 16

**Files:**
- Modify: `backend/app/services/ai_enrich.py`
- Test: `backend/tests/test_ai_enrich.py`(新建或已存在则扩)

- [x] **Step 1: 读现状**

Read `backend/app/services/ai_enrich.py`. Locate the system/user prompt that constrains `cn_meaning` length (explorer noted "≤ 40"). Also locate the post-call hard cap on the returned `cn_meaning`.

- [x] **Step 2: 写失败测试**

```python
# backend/tests/test_ai_enrich.py
from app.services import ai_enrich

def test_prompt_requires_meaning_within_16_chars(monkeypatch):
    captured = {}
    class FakeResp:
        status_code = 200
        def raise_for_status(self): pass
        def json(self): return {"choices": [{"message": {"content": '{"cn_meaning":"相机","phonetic":null,"example_sentence":null}'}}]}
    def fake_post(client, url, *, json, headers):
        captured["body"] = json
        return FakeResp()
    monkeypatch.setattr(ai_enrich, "_post", fake_post, raising=False)  # adjust to actual helper name
    monkeypatch.setattr(ai_enrich, "get_settings", lambda: __import__("types").SimpleNamespace(ai_base_url="https://ai", ai_api_key="k", ai_model="m", ai_timeout=10))
    ai_enrich.ai_enrich_word("camera")
    body_text = str(captured["body"])
    assert "16" in body_text  # prompt mentions the 16-char limit
```

> If `_post`/helper names differ, first read the file and target the real function that builds the request body (likely builds a `messages` list). Assert on that list's text content containing "16".

- [x] **Step 3: 运行确认失败** → FAIL.

- [x] **Step 4: 改 prompt + 返回兜底**

In `ai_enrich.py`, change the constraint text from 40 to 16(e.g. "中文释义不超过 16 个汉字"). After parsing the AI JSON, enforce a hard cap:
```python
if cn and len(cn) > 16:
    cn = cn[:15].rstrip(" ；;,，.。、") + "…"
```

- [x] **Step 5: 运行确认通过** → PASS.

- [x] **Step 6: 提交**

```bash
git add backend/app/services/ai_enrich.py backend/tests/test_ai_enrich.py
git commit -m "feat(ai-enrich): constrain AI meanings to ≤16 chars

Co-Authored-By: Claude <noreply@anthropic.com>"
```

### Task B4: `/words/import` 响应返回 `resolved[]`(word_id)

**Files:**
- Modify: `backend/app/api/words.py:253-426`
- Test: `backend/tests/test_words_import.py`

- [x] **Step 1: 写失败测试**

```python
# append to backend/tests/test_words_import.py
def test_import_returns_resolved_word_ids(client, db_session, admin_headers):
    # pre-create one word so it is 'skipped' under conflict_policy=skip
    from app.services.words import create_word
    from app.schemas import WordCreate
    create_word(db_session, enrich_stub(WordCreate(en_word="camera", cn_meaning="相机")))
    db_session.commit()
    resp = client.post(
        "/api/v1/words/import",
        headers={**admin_headers, "Content-Type": "multipart/form-data"},
        data={"conflict_policy": "skip", "unresolved_policy": "skip"},
        files={"file": ("words.txt", b"camera\nfocus\n", "text/plain")},
    )
    assert resp.status_code == 200
    resolved = resp.json()["data"]["resolved"]
    by_word = {r["en_word"]: r for r in resolved}
    assert by_word["camera"]["action"] == "skipped"
    assert isinstance(by_word["camera"]["word_id"], int)
    assert by_word["focus"]["action"] == "created"
    assert isinstance(by_word["focus"]["word_id"], int)
```

> `enrich_stub`/`admin_headers`/`client`/`db_session` fixtures come from `conftest.py`; reuse the patterns already in `test_words_import.py`. If `create_word` returns the `Word`, use `.id`; otherwise query after.

- [x] **Step 2: 运行确认失败**

Run: `cd backend && .venv/bin/pytest tests/test_words_import.py -v`
Expected: FAIL(`resolved` key absent).

- [x] **Step 3: 实现**

In `backend/app/api/words.py` `import_words`:
- Initialize `resolved: list[dict] = []` next to `created = updated = skipped = 0`.
- In the per-row loop, capture the word id:
  - **created**: `word = create_word(db, payload); resolved.append({"en_word": payload.en_word, "word_id": word.id, "action": "created"})` (if `create_word` doesn't return the Word, do `existing = db.scalar(select(Word).where(Word.normalized_en_word == normalized)); resolved.append(... word_id=existing.id ...)`).
  - **updated / restored (deleted_at)**: `resolved.append({"en_word": payload.en_word, "word_id": existing.id, "action": "updated"})`.
  - **skipped (existing, conflict_policy=skip)**: `resolved.append({"en_word": payload.en_word, "word_id": existing.id, "action": "skipped"})`.
  - **in-file duplicate skipped**: append with the first occurrence's id, action `"skipped"`.
- For unresolved (dropped) words: append `{"en_word": word, "word_id": None, "action": "unresolved"}` where `unresolved_words` is collected.
- Add `"resolved": resolved,` to the `data` dict (line ~382).

- [x] **Step 4: 运行确认通过**

Run: `cd backend && .venv/bin/pytest tests/test_words_import.py -v`
Expected: PASS.

- [x] **Step 5: 提交**

```bash
git add backend/app/api/words.py backend/tests/test_words_import.py
git commit -m "feat(words): import response includes resolved word_ids

Co-Authored-By: Claude <noreply@anthropic.com>"
```

### Task B5: 前端 txt 导入选词面板

**Files:**
- Modify: `frontend/src/views/DailyGenerateView.vue`、`frontend/src/api/words.ts`
- Test: `frontend/tests/unit/dailyGenerate.spec.ts`(新建)

- [x] **Step 1: 写失败测试(txt 解析 + 去重)**

```ts
// frontend/tests/unit/dailyGenerate.spec.ts
import { describe, expect, it } from 'vitest'
import { parseWordText } from '@/views/dailyGenerateLogic'

describe('parseWordText', () => {
  it('splits on newlines / commas / whitespace and dedupes case-insensitively', () => {
    expect(parseWordText('camera\nfocus, Camera  focus\n  ')).toEqual(['camera', 'focus'])
  })
  it('drops blanks and comment lines', () => {
    expect(parseWordText('# comment\n\n  \nword')).toEqual(['word'])
  })
})
```

- [x] **Step 2: 运行确认失败** → FAIL.

- [x] **Step 3: 实现纯逻辑**

```ts
// frontend/src/views/dailyGenerateLogic.ts
export function parseWordText(raw: string): string[] {
  const seen = new Set<string>()
  const out: string[] = []
  for (const token of raw.split(/[\s,，;；]+/)) {
    const w = token.trim()
    if (!w || w.startsWith('#')) continue
    const key = w.toLowerCase()
    if (seen.has(key)) continue
    seen.add(key)
    out.push(w)
  }
  return out
}
```

- [x] **Step 4: 运行确认通过** → PASS.

- [x] **Step 5: 在 `DailyGenerateView.vue` 加面板**

Read the file. In the custom-selection area (near the existing `el-select` bound to `form.word_ids`), add a collapsible panel:
- `<el-input type="textarea" :rows="6" v-model="txtInput" placeholder="每行一个英文单词，支持逗号/空格分隔" />`
- `<el-button @click="onParseTxt">解析</el-button>` → computes `parsedWords = parseWordText(txtInput)` and shows them as chips with a count.
- `<el-button type="primary" :loading="importing" :disabled="!parsedWords.length" @click="onImportAndGenerate">导入并生成</el-button>`:
  ```ts
  async function onImportAndGenerate() {
    importing.value = true
    try {
      const file = new File([parsedWords.value.join('\n')], 'words.txt', { type: 'text/plain' })
      const fd = new FormData()
      fd.append('file', file)
      fd.append('conflict_policy', 'skip')
      fd.append('unresolved_policy', 'ai')
      const res = await importWords(fd)             // from @/api/words
      const ids = (res.resolved ?? []).filter(r => r.word_id).map(r => r.word_id)
      form.value.word_ids = ids
      // then trigger the existing generate flow with these word_ids
      await generate()                                // existing handler
    } finally { importing.value = false }
  }
  ```
- In `frontend/src/api/words.ts`, type the import response:
  ```ts
  export interface ImportResolved { en_word: string; word_id: number | null; action: string }
  export interface ImportResult { created: number; updated: number; skipped: number; unresolved: number; total: number; resolved: ImportResolved[] }
  ```
  Ensure `importWords` returns the unwrapped `ImportResult` (it already POSTs multipart; add the return type).

- [x] **Step 6: typecheck + test + build**

Run: `cd frontend && npm run typecheck && npm test && npm run build`
Expected: PASS.

- [x] **Step 7: 提交**

```bash
git add frontend/src/views/dailyGenerateLogic.ts frontend/src/views/DailyGenerateView.vue frontend/src/api/words.ts frontend/tests/unit/dailyGenerate.spec.ts
git commit -m "feat(daily): txt import for custom word selection (dedupe + AI enrich)

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Phase C — 复习表 / md / pdf 排版(#4)

### Task C1: `PracticeWorksheet` 合并列/不画线/例句全显/斜杠

**Files:**
- Modify: `frontend/src/components/PracticeWorksheet.vue`、`frontend/src/styles/print.css`
- Test: `frontend/tests/unit/practiceWorksheet.spec.ts`(新建)

- [x] **Step 1: 写失败测试(渲染)**

```ts
// frontend/tests/unit/practiceWorksheet.spec.ts
import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import PracticeWorksheet from '@/components/PracticeWorksheet.vue'

const session: any = {
  session_id: 1, items: [{ item_id: 1, position: 1, word: { en_word: 'camera', phonetic: 'ˈkæmərə', cn_meaning: '相机', example_sentence: 'I have a camera.' } }],
}
describe('PracticeWorksheet', () => {
  it('shows word + /phonetic/ on one line in the same cell', () => {
    const w = mount(PracticeWorksheet, { props: { session, answer: false, mode: 'en-to-cn' } })
    const cell = w.get('.word-cell')
    expect(cell.text()).toContain('camera')
    expect(cell.text()).toContain('/ˈkæmərə/')
  })
  it('does NOT draw underlines for the blanked side', () => {
    const w = mount(PracticeWorksheet, { props: { session, answer: false, mode: 'cn-to-en' } }) // English blanked
    const cell = w.get('.word-cell')
    expect(cell.text()).not.toContain('___')
    expect(cell.text().trim()).toBe('')
  })
  it('shows the full example sentence (no fill-in-blank)', () => {
    const w = mount(PracticeWorksheet, { props: { session, answer: false, mode: 'en-to-cn' } })
    expect(w.get('.example-cell').text()).toContain('I have a camera.')
    expect(w.get('.example-cell').text()).not.toContain('_____')
  })
})
```

- [x] **Step 2: 运行确认失败**

Run: `cd frontend && npm test -- practiceWorksheet`
Expected: FAIL(`.word-cell` absent; current template has separate 英文/音标 columns + `____`).

- [x] **Step 3: 改组件**

Read `frontend/src/components/PracticeWorksheet.vue`. Replace the `english()/chinese()/example()` helpers and the table:
```ts
import { formatPhonetic } from '@/utils/formatPhonetic'

function wordCell(item: PracticeItem) {
  // In cn-to-en recall the English side is blanked (empty string, no underline).
  if (props.answer || props.mode !== 'cn-to-en') {
    const ph = formatPhonetic(item.word.phonetic)
    return ph ? `${item.word.en_word} ${ph}` : item.word.en_word
  }
  return ''
}
function chinese(item: PracticeItem) {
  // en-to-cn blanks the Chinese side (empty string, no underline).
  return props.answer || props.mode !== 'en-to-cn' ? (item.word.cn_meaning || '') : ''
}
function example(item: PracticeItem) {
  return item.word.example_sentence || ''
}
```
Template: merge the 英文 + 音标 `<th>`/`<td>` into one column whose `<td class="word-cell">{{ wordCell(item) }}</td>`. Remove the separate 音标 column. Keep 序号 / (单词 /音标) / 中文 / 例句 = 4 columns now. Update the `colspan` on the header row accordingly.

- [x] **Step 4: 加 CSS**

In `frontend/src/styles/print.css`, add:
```css
.worksheet-table .word-cell { white-space: nowrap !important; }
```
(Keep existing `.english-cell`/`.example-cell` rules; `.word-cell` replaces the english column’s no-wrap need.)

- [x] **Step 5: 运行确认通过**

Run: `cd frontend && npm test -- practiceWorksheet && npm run typecheck`
Expected: PASS.

- [x] **Step 6: 提交**

```bash
git add frontend/src/components/PracticeWorksheet.vue frontend/src/styles/print.css frontend/tests/unit/practiceWorksheet.spec.ts
git commit -m "feat(worksheet): word+/phonetic/ one line, no underlines, full example

Co-Authored-By: Claude <noreply@anthropic.com>"
```

### Task C2: `build_recitation_md` 词+音标同格 + 斜杠

**Files:**
- Modify: `backend/app/services/recitation.py`
- Test: `backend/tests/test_recitation.py`

- [x] **Step 1: 写失败测试**

```python
# append to backend/tests/test_recitation.py
from app.services.recitation import build_recitation_md

def _item(en, ph, cn, ex):
    from types import SimpleNamespace
    return SimpleNamespace(snapshot_en_word=en, snapshot_phonetic=ph, snapshot_cn_meaning=cn, snapshot_example_sentence=ex)

def test_recitation_md_merges_word_and_phonetic_with_slashes():
    md = build_recitation_md([_item("camera", "ˈkæmərə", "相机", "I have a camera.")])
    # word + /phonetic/ share the first cell
    assert "| camera /ˈkæmərə/ |" in md
    assert "| 相机 |" in md
    # example shown in full
    assert "I have a camera." in md

def test_recitation_md_omits_slashes_when_no_phonetic():
    md = build_recitation_md([_item("focus", None, "焦点", "Stay focused.")])
    assert "| focus |" in md
    assert "//" not in md
```

- [x] **Step 2: 运行确认失败** → FAIL(currently 4 columns, no slashes).

- [x] **Step 3: 改 `build_recitation_md`**

In `backend/app/services/recitation.py`:
```python
def _format_phonetic(p: str | None) -> str:
    if not p:
        return ""
    t = p.strip().strip("/")
    return f"/{t}/" if t else ""

def build_recitation_md(items):
    lines = ["# 📚 单词背诵表", "", "|单词 /音标/|中文|例句|", "|---|---|---|"]
    for item in items:
        word = _cell(item.snapshot_en_word)
        ph = _format_phonetic(item.snapshot_phonetic)
        first = f"{word} {ph}".strip() if word else ph
        lines.append(f"|{first}|{_cell(item.snapshot_cn_meaning)}|{_cell(item.snapshot_example_sentence)}|")
    lines.extend(["", "> 💡 遮住右侧，看中文回忆英文，反复 3 遍即可牢记！", ""])
    return "\n".join(lines)
```
(Keep `_cell` as-is.)

- [x] **Step 4: 运行确认通过**

Run: `cd backend && .venv/bin/pytest tests/test_recitation.py -v`
Expected: PASS.

- [x] **Step 5: 提交**

```bash
git add backend/app/services/recitation.py backend/tests/test_recitation.py
git commit -m "feat(recitation): word + /phonetic/ in one md cell

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Phase D — 管理员工具:API 令牌 + 全量备份(#6 + #7)

### Task D1: API client 请求 schemas

**Files:**
- Modify: `backend/app/schemas/contracts.py`
- Test: 现有 contracts 校验测试(若有)

- [x] **Step 1: 读现状**

Read `backend/app/schemas/contracts.py` — note the `StrictModel` base, `Literal` usage, `Field` patterns.

- [x] **Step 2: 加 schemas**

```python
# append to backend/app/schemas/contracts.py
class ApiClientCreateRequest(StrictModel):
    name: str = Field(min_length=1, max_length=100)
    skill_name: str = Field(min_length=1, max_length=100)
    skill_version: str = Field(min_length=1, max_length=50)
    scopes: list[str] = Field(min_length=1, max_length=20)
    expires_days: int = Field(default=365, ge=1, le=3650)
    description: str | None = Field(default=None, max_length=500)

class ApiClientUpdateRequest(StrictModel):
    scopes: list[str] | None = Field(default=None, min_length=1, max_length=20)
    description: str | None = Field(default=None, max_length=500)
    status: Literal["active", "disabled"] | None = None

    @model_validator(mode="after")
    def _at_least_one(self):
        if self.scopes is None and self.description is None and self.status is None:
            raise ValueError("至少需要提供 scopes / description / status 之一")
        return self
```
Ensure `Literal`, `model_validator` are imported (they are, per existing `UserUpdateRequest`).

- [x] **Step 3: 运行(ruff + 导入冒烟)**

Run: `cd backend && .venv/bin/ruff check app/schemas/contracts.py && .venv/bin/python -c "from app.schemas.contracts import ApiClientCreateRequest"`
Expected: clean + import OK.

- [x] **Step 4: 提交**

```bash
git add backend/app/schemas/contracts.py
git commit -m "feat(contracts): API client create/update request schemas

Co-Authored-By: Claude <noreply@anthropic.com>"
```

### Task D2: API client 管理路由 + 测试

**Files:**
- Create: `backend/app/api/api_clients.py`
- Modify: `backend/app/main.py`(register router + OpenAPI skip)
- Test: `backend/tests/test_api_clients_admin.py`

- [x] **Step 1: 写失败测试**

```python
# backend/tests/test_api_clients_admin.py
def test_admin_creates_client_and_gets_plaintext_token_once(client, admin_session):
    resp = client.post("/api/v1/api-clients", json={
        "name": "add-words", "skill_name": "add-words", "skill_version": "1.0.0",
        "scopes": ["words:write"], "expires_days": 30,
    })
    assert resp.status_code == 201
    data = resp.json()["data"]
    assert data["token"].startswith("wm_")
    cid = data["id"]
    # listing must NOT include the plaintext token or any hash
    listing = client.get("/api/v1/api-clients", headers=admin_session)
    item = next(x for x in listing.json()["data"] if x["id"] == cid)
    assert "token" not in item
    assert "token_hash" not in item
    assert "words:write" in item["scopes"]

def test_student_forbidden(client, student_session):
    assert client.get("/api/v1/api-clients", headers=student_session).status_code == 403
    assert client.post("/api/v1/api-clients", headers=student_session, json={...}).status_code == 403

def test_rotate_returns_new_token_and_revokes_old(client, admin_session):
    # create, then POST /{id}/tokens → new token; old token no longer authenticates
    ...

def test_disable_client(client, admin_session):
    # PATCH /{id} status=disabled → status reflected; token auth fails
    ...
```

> `admin_session`/`student_session` fixtures: reuse the cookie-login pattern from `test_web_login.py` / `test_users_admin.py` (log in via `/api/v1/auth/login` and pass the session cookie). If those fixtures aren't shared, copy the login helper.

- [x] **Step 2: 运行确认失败** → FAIL(404 no route).

- [x] **Step 3: 实现路由**

Create `backend/app/api/api_clients.py` (mirrors `app/api/users.py` structure — same `_request_id`/`_commit`/`add_audit` patterns):
```python
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.audit import add_audit
from app.core.auth import (
    ALL_SCOPES,
    Actor,
    create_api_client_token,
    generate_token,
    hash_token,
    require_web_admin,
    token_prefix,
)
from app.core.config import get_settings
from app.core.database import get_db
from app.core.errors import AppError, not_found
from app.core.responses import envelope
from app.models import ApiClient, ApiClientScope, ApiClientToken
from app.schemas import ApiClientCreateRequest, ApiClientUpdateRequest
from app.services.domain import parse_utc, utc_text

router = APIRouter(prefix="/api/v1/api-clients", tags=["api-clients"])


def _request_id(request: Request) -> str:
    return request.state.request_id


def _commit(db: Session) -> None:
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise


def _get(db: Session, client_id: int) -> ApiClient:
    client = db.get(ApiClient, client_id)
    if client is None:
        raise not_found("api_client")
    return client


def _serialize(db: Session, c: ApiClient) -> dict:
    scopes = db.scalars(
        select(ApiClientScope.scope).where(ApiClientScope.api_client_id == c.id)
    ).all()
    tokens = db.scalars(
        select(ApiClientToken)
        .where(ApiClientToken.api_client_id == c.id)
        .order_by(ApiClientToken.id)
    ).all()
    now = datetime.now(UTC)
    return {
        "id": c.id, "name": c.name, "description": c.description,
        "skill_name": c.skill_name, "skill_version": c.skill_version, "status": c.status,
        "scopes": sorted(scopes),
        "tokens": [{
            "id": t.id, "prefix": t.token_prefix,
            "state": "revoked" if t.revoked_at is not None
            else ("expired" if parse_utc(t.expires_at) <= now else "active"),
            "expires_at": t.expires_at, "last_used_at": t.last_used_at,
        } for t in tokens],
        "created_at": c.created_at,
    }


@router.get("")
def list_clients(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    _actor: Annotated[Actor, Depends(require_web_admin)],
):
    clients = db.scalars(select(ApiClient).order_by(ApiClient.id.desc())).all()
    return envelope(request, [_serialize(db, c) for c in clients])


@router.post("", status_code=201)
def create_client(
    request: Request,
    payload: ApiClientCreateRequest,
    db: Annotated[Session, Depends(get_db)],
    actor: Annotated[Actor, Depends(require_web_admin)],
):
    # create_api_client_token() validates scopes against ALL_SCOPES, creates the
    # client + scopes + token, writes its own "system" audit row, and commits.
    client, _token, raw = create_api_client_token(
        db,
        name=payload.name, skill_name=payload.skill_name, skill_version=payload.skill_version,
        scopes=payload.scopes, expires_days=payload.expires_days, description=payload.description,
    )
    data = _serialize(db, client)
    data["token"] = raw  # plaintext token, surfaced only in this response
    return envelope(request, data, status_code=201)


@router.post("/{client_id}/tokens")
def rotate_token(
    request: Request,
    client_id: int,
    db: Annotated[Session, Depends(get_db)],
    actor: Annotated[Actor, Depends(require_web_admin)],
):
    _get(db, client_id)  # raises 404 if missing
    now = datetime.now(UTC)
    # revoke all currently-active tokens immediately
    for t in db.scalars(select(ApiClientToken).where(
        ApiClientToken.api_client_id == client_id, ApiClientToken.revoked_at.is_(None)
    )):
        t.revoked_at = utc_text(now)
    db.flush()
    raw_token = generate_token()
    db.add(ApiClientToken(
        api_client_id=client_id, token_prefix=token_prefix(raw_token),
        token_hash=hash_token(raw_token, get_settings()), created_at=utc_text(now),
        expires_at=utc_text(now + timedelta(days=365)),
    ))
    add_audit(
        db, request_id=_request_id(request), actor=actor,
        action="api_client.rotate_token", outcome="success", http_status=200,
        target_type="api_client", target_id=client_id,
    )
    _commit(db)
    return envelope(request, {"token": raw_token})


@router.patch("/{client_id}")
def update_client(
    request: Request,
    client_id: int,
    payload: ApiClientUpdateRequest,
    db: Annotated[Session, Depends(get_db)],
    actor: Annotated[Actor, Depends(require_web_admin)],
):
    client = _get(db, client_id)
    if payload.status is not None:
        client.status = payload.status
    if payload.description is not None:
        client.description = payload.description
    if payload.scopes is not None:
        unknown = set(payload.scopes) - ALL_SCOPES
        if unknown:
            raise AppError(422, "VALIDATION_ERROR", "包含未知的授权范围", [{"unknown": sorted(unknown)}])
        db.query(ApiClientScope).filter(ApiClientScope.api_client_id == client_id).delete()
        for sc in sorted(set(payload.scopes)):
            db.add(ApiClientScope(api_client_id=client_id, scope=sc))
        client.scope_version = (client.scope_version or 0) + 1
    client.updated_at = utc_text()
    add_audit(
        db, request_id=_request_id(request), actor=actor,
        action="api_client.update", outcome="success", http_status=200,
        target_type="api_client", target_id=client_id,
        metadata={"status": payload.status, "scopes": payload.scopes},
    )
    _commit(db)
    return envelope(request, _serialize(db, client))


@router.delete("/{client_id}", status_code=204)
def disable_client(
    request: Request,
    client_id: int,
    db: Annotated[Session, Depends(get_db)],
    actor: Annotated[Actor, Depends(require_web_admin)],
):
    client = _get(db, client_id)
    client.status = "disabled"
    client.updated_at = utc_text()
    add_audit(
        db, request_id=_request_id(request), actor=actor,
        action="api_client.disable", outcome="success", http_status=204,
        target_type="api_client", target_id=client_id,
    )
    _commit(db)
    return Response(status_code=204)


@router.delete("/{client_id}/tokens/{token_id}", status_code=204)
def revoke_token(
    request: Request,
    client_id: int,
    token_id: int,
    db: Annotated[Session, Depends(get_db)],
    actor: Annotated[Actor, Depends(require_web_admin)],
):
    _get(db, client_id)
    t = db.get(ApiClientToken, token_id)
    if t is None or t.api_client_id != client_id:
        raise not_found("api_token")
    t.revoked_at = utc_text()
    add_audit(
        db, request_id=_request_id(request), actor=actor,
        action="api_token.revoke", outcome="success", http_status=204,
        target_type="api_token", target_id=token_id,
    )
    _commit(db)
    return Response(status_code=204)
```

**Also edit `backend/app/core/errors.py`** — add two resource keys to `_RESOURCE_ZH` so `not_found(...)` renders Chinese:
```python
    "api_client": "API 客户端",
    "api_token": "API 令牌",
```

- [x] **Step 4: 注册路由 + OpenAPI 跳过**

In `backend/app/main.py`:
- import: `from app.api.api_clients import router as api_clients_router`
- register: `app.include_router(api_clients_router)` alongside `auth_router`/`users_router`.
- In `custom_openapi`'s security-annotation loop (the one that already skips `/api/v1/auth` and `/api/v1/users`), also skip paths starting with `/api/v1/api-clients`. Leave `x-required-scopes` empty for them (role-gated).

- [x] **Step 5: 运行测试**

Run: `cd backend && .venv/bin/pytest tests/test_api_clients_admin.py -v`
Expected: PASS.

- [x] **Step 6: 提交**

```bash
git add backend/app/api/api_clients.py backend/app/main.py backend/app/core/errors.py backend/tests/test_api_clients_admin.py
git commit -m "feat(api-clients): admin CRUD routes for API clients (role-gated)

Co-Authored-By: Claude <noreply@anthropic.com>"
```

### Task D3: SQLite 全量备份下载 + 测试

**Files:**
- Create: `backend/app/api/system.py`
- Modify: `backend/app/main.py`(register)
- Test: `backend/tests/test_system_backup.py`

- [x] **Step 1: 写失败测试**

```python
# backend/tests/test_system_backup.py
import sqlite3
def test_admin_downloads_valid_sqlite(client, admin_session):
    resp = client.get("/api/v1/system/backup", headers=admin_session)
    assert resp.status_code == 200
    assert resp.headers["content-disposition"].startswith("attachment; filename=\"vocab-")
    assert resp.headers["content-disposition"].endswith(".db\"")
    # body is a valid sqlite file
    import tempfile, os
    fd, path = tempfile.mkstemp(suffix=".db")
    os.write(fd, resp.content); os.close(fd)
    con = sqlite3.connect(path)
    assert con.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    assert con.execute("SELECT count(*) FROM words").fetchone()[0] >= 0
    con.close(); os.remove(path)

def test_student_forbidden(client, student_session):
    assert client.get("/api/v1/system/backup", headers=student_session).status_code == 403
```

- [x] **Step 2: 运行确认失败** → FAIL(404).

- [x] **Step 3: 实现路由**

Create `backend/app/api/system.py`. `settings.database_url` (confirmed attr in `app/core/config.py:24`, default `sqlite:///./data/vocab.db`) is the live DB; the SQLite online `backup()` API is safe under WAL writes. `BackgroundTask` deletes the temp file after the stream completes:
```python
from __future__ import annotations

import os
import sqlite3
import tempfile
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.responses import FileResponse
from starlette.background import BackgroundTask

from app.core.auth import Actor, require_web_admin
from app.core.config import get_settings

router = APIRouter(prefix="/api/v1/system", tags=["system"])


def _sqlite_path(database_url: str) -> str:
    if database_url.startswith("sqlite:///"):
        return database_url[len("sqlite:///"):]
    if database_url.startswith("sqlite://"):
        return database_url[len("sqlite://"):]
    return database_url or "vocab.db"


@router.get("/backup")
def download_backup(_actor: Annotated[Actor, Depends(require_web_admin)]):
    src_path = _sqlite_path(get_settings().database_url)
    dst_fd, dst_path = tempfile.mkstemp(suffix=".db", prefix="vocab-backup-")
    os.close(dst_fd)
    src = sqlite3.connect(src_path)
    dst = sqlite3.connect(dst_path)
    try:
        src.backup(dst)  # online snapshot; includes WAL contents
    finally:
        dst.close()
        src.close()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    return FileResponse(
        dst_path,
        media_type="application/octet-stream",
        filename=f"vocab-{stamp}.db",
        background=BackgroundTask(os.remove, dst_path),
    )
```

- [x] **Step 4: 注册路由**

In `backend/app/main.py`: `from app.api.system import router as system_router` and `app.include_router(system_router)`. Add `/api/v1/system` to the OpenAPI security-skip set (role-gated, no BearerAuth/TrustedProxyUser).

- [x] **Step 5: 运行测试**

Run: `cd backend && .venv/bin/pytest tests/test_system_backup.py -v`
Expected: PASS.

- [x] **Step 6: 提交**

```bash
git add backend/app/api/system.py backend/app/main.py backend/tests/test_system_backup.py
git commit -m "feat(system): admin SQLite full-backup download endpoint

Co-Authored-By: Claude <noreply@anthropic.com>"
```

### Task D4: 前端「系统管理」页(`/system`)+ API client 管理 + 备份按钮

**Files:**
- Create: `frontend/src/api/apiClients.ts`、`frontend/src/views/SystemView.vue`
- Modify: `frontend/src/types/domain.ts`、`frontend/src/router/index.ts`、`frontend/src/layouts/AppShell.vue`
- Test: `frontend/tests/unit/systemView.spec.ts`(新建,可选轻量)

- [x] **Step 1: 加类型 + API**

`frontend/src/types/domain.ts`:
```ts
export interface ApiClientTokenInfo { id: number; prefix: string; state: string; expires_at: string; last_used_at: string | null }
export interface ApiClient { id: number; name: string; description: string | null; skill_name: string; skill_version: string; status: string; scopes: string[]; tokens: ApiClientTokenInfo[]; created_at: string }
export interface ApiClientCreated extends ApiClient { token: string }
export interface ApiClientCreatePayload { name: string; skill_name: string; skill_version: string; scopes: string[]; expires_days: number; description?: string }
export interface ApiClientUpdatePayload { scopes?: string[]; description?: string; status?: 'active' | 'disabled' }
export const ALL_SCOPES = ['words:read','words:write','words:export','practice:generate','practice:read','practice:write','reviews:write','reviews:read'] as const
```

`frontend/src/api/apiClients.ts`:
```ts
import { apiClient, unwrap } from './client'
import type { ApiClient, ApiClientCreated, ApiClientCreatePayload, ApiClientUpdatePayload } from '@/types/domain'

export const listApiClients = () => unwrap<ApiClient[]>(apiClient.get('/api-clients'))
export const createApiClient = (p: ApiClientCreatePayload) => unwrap<ApiClientCreated>(apiClient.post('/api-clients', p))
export const rotateApiToken = (id: number) => unwrap<{ token: string }>(apiClient.post(`/api-clients/${id}/tokens`))
export const updateApiClient = (id: number, p: ApiClientUpdatePayload) => unwrap<ApiClient>(apiClient.patch(`/api-clients/${id}`, p))
export const disableApiClient = (id: number) => apiClient.delete(`/api-clients/${id}`)
export const revokeApiToken = (id: number, tokenId: number) => apiClient.delete(`/api-clients/${id}/tokens/${tokenId}`)
```
(Check `apiClient` base path is `/api/v1` so `/api-clients` resolves correctly — it is, per CLAUDE.md.)

- [x] **Step 2: 写 `SystemView.vue`**

Two sections:
1. **API 令牌管理**: `el-table` of `ApiClient` (name/skill/scopes/status/tokens); 「新增」opens a dialog (name/skill_name/skill_version/scopes=`el-checkbox-group` from `ALL_SCOPES`/expires_days/description) → on create, show a one-time `el-dialog` with the plaintext `token`, a copy button, and warning「请立即保存,关闭后不再显示」. Row actions: 轮换(shows new token dialog)/改 scope/启用-禁用/撤销 token.
2. **数据备份**: a button 「下载整库备份(.db)」 that calls `GET /api/v1/system/backup` as a blob and triggers a browser download (reuse the existing blob-download pattern from `api/words.ts` export). Plus the restore instruction text from the spec.

Skeleton:
```vue
<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import * as api from '@/api/apiClients'
import type { ApiClient, ApiClientCreatePayload } from '@/types/domain'
import { ALL_SCOPES } from '@/types/domain'
import { apiClient, normalizeApiError } from '@/api/client'

const clients = ref<ApiClient[]>([])
const loading = ref(false)
async function load(){ loading.value=true; try{ clients.value = await api.listApiClients() } finally { loading.value=false } }
onMounted(load)
// create dialog state, plaintext-token-once dialog state, rotate/disable/revoke handlers
// (mirror the patterns in UsersView.vue: ElMessageBox.confirm for destructive actions,
//  ElMessage.success on success, normalizeApiError(e).message on failure)

async function downloadBackup(){
  try {
    const res = await apiClient.get('/system/backup', { responseType: 'blob' })
    const url = URL.createObjectURL(res.data)
    const a = document.createElement('a'); a.href = url
    a.download = 'vocab-backup.db'
    document.body.appendChild(a); a.click(); a.remove(); URL.revokeObjectURL(url)
  } catch (e) { ElMessage.error(normalizeApiError(e).message) }
}
</script>
<template>
  <section class="system-page">
    <div class="panel"><h2>API 令牌(外部 Skill 接入)</h2> ...table + dialogs... </div>
    <div class="panel"><h2>数据备份</h2>
      <el-button type="primary" @click="downloadBackup">下载整库备份(.db)</el-button>
      <p class="muted">该文件可还原整库(词库 + 复习历史 + 会话)。还原:停容器 → 替换 data/vocab.db → 起容器。</p>
    </div>
  </section>
</template>
```

- [x] **Step 3: 路由 + 侧栏**

`frontend/src/router/index.ts`: add
```ts
{ path: 'system', name: 'system', component: () => import('@/views/SystemView.vue'),
  meta: { label: '系统', shortLabel: '系统', icon: '⚙', title: '系统管理', roles: ['admin'], nav: true } }
```
`AppShell.vue`: nav already filters by `meta.roles` and `meta.nav` — verify 「系统」 appears for admin only (it will, given `roles:['admin']`).

- [x] **Step 4: typecheck + test + build**

Run: `cd frontend && npm run typecheck && npm test && npm run build`
Expected: PASS (SystemView chunk in build output).

- [x] **Step 5: 提交**

```bash
git add frontend/src/api/apiClients.ts frontend/src/views/SystemView.vue frontend/src/types/domain.ts frontend/src/router/index.ts frontend/src/layouts/AppShell.vue frontend/tests/unit/systemView.spec.ts
git commit -m "feat(system): admin UI for API token management + backup download

Co-Authored-By: Claude <noreply@anthropic.com>"
```

### Task D5: 契约重生成 + 文档

**Files:**
- Modify: `backend/contracts/openapi.yaml`(regenerated)、`CLAUDE.md`、`deploy/README.md`

- [x] **Step 1: 重生成 OpenAPI**

Run: `cd backend && .venv/bin/python scripts/export_openapi.py`
Then: `cd backend && git diff --exit-code -- contracts/openapi.yaml`
Expected: diff present (new `/api/v1/api-clients/*`, `/api/v1/system/backup`, import `resolved` field); exit 0 after staging.

- [x] **Step 2: 更新 CLAUDE.md**

- 认证/授权段:补 `/api/v1/api-clients`(role-gated via `require_web_admin`,不进 `REQUIRED_SCOPES`,明文 token 仅创建/轮换返回一次);`/api/v1/system/backup`(admin SQLite 下载)。
- 词库段:释义上限 16 字(`shorten_translations(target=16)` + 多边界符)+ >16 走 AI(`ai_enabled` 时)。
- 复习表段:词+/音标/同行;例句全显;留空不画线。
- 前端约定:`/system` 路由;`formatPhonetic` util。

- [x] **Step 3: 更新 deploy/README.md**

新增「数据备份下载」:管理员后台「系统 → 数据备份」一键下载 `.db`;更新前用它替代/补充 `docker exec` 备份;还原步骤。

- [x] **Step 4: 全量回归**

Run:
```
cd backend && .venv/bin/ruff check app tests && .venv/bin/pytest -q
cd frontend && npm run typecheck && npm test && npm run build
```
Expected: all green.

- [x] **Step 5: 提交**

```bash
git add backend/contracts/openapi.yaml CLAUDE.md deploy/README.md
git commit -m "docs: phase 6 — token mgmt, backup, 16-char meanings, worksheet layout

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Self-Review

**1. Spec coverage:**
- #1 复习下一题/末题置灰 → Task A1 ✓
- #5 学员只读汇总 → Task A2 ✓
- #2 缩短 + AI 重译(新词) → B1 + B2 + B3 ✓
- #3 txt 导入沉淀词库去重 → B4(响应 ID)+ B5(前端)✓
- #4 复习表/md/pdf 排版 → C1(前端)+ C2(md/pdf)✓;音标斜杠在 0.1 + C1 + C2 + A2 全覆盖 ✓
- #6 token 完整管理 UI → D1 + D2 + D4 ✓
- #7 SQLite 备份 → D3 + D4 ✓
- 契约/文档 → D5 ✓

**2. Placeholder scan:** D2 and D3 now contain concrete, signature-verified code (`add_audit` keyword args via `_request_id(request)`; `settings.database_url`; `not_found` resource keys added to `_RESOURCE_ZH`; `BackgroundTask(os.remove, ...)` cleanup; `generate_token`/`hash_token`/`token_prefix` reused from `core/auth`). B3's test targets the AI prompt-builder (executor reads `ai_enrich.py` first to name the real helper). No TBDs, no broken code blocks.

**3. Type consistency:** `formatPhonetic` used identically in 0.1/A2/C1. `summarize`/`nextButtonLabel`/`nextButtonDisabled` defined in `reviewLogic.ts` (A1/A2) and imported consistently. `parseWordText` (B5) defined and tested. Backend `shorten_translations` uses `target=16, min_keep=10`; the removed `hard_cap` parameter has no stale callers. `ApiClient`/`ApiClientCreated` shapes match between D1 schemas, D2 serialize, D4 frontend types.

**4. Ambiguity:** rotate-token "immediately revoke old" is explicit (D2). Import `resolved[].action ∈ created|updated|skipped|unresolved` explicit (B4). Worksheet recall modes: en-to-cn blanks Chinese, cn-to-en blanks English (empty string, no underline) — explicit (C1).
