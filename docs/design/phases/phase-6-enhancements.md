# 阶段六增强批次 — 设计规格

- **日期**:2026-07-22
- **范围**:在线复习 UX、词库释义缩短/AI 重译、txt 导入选词、复习表/md/pdf 排版、学员只读结果、API 令牌管理 UI、全量备份
- **定位**:一个增强批次(非独立子系统),分 4 组,按组增量实现与提交。遵守现有四层分层(routes→services→models→schemas)、`AppError` 错误契约、scope/role 门禁、OpenAPI 契约重生成。

## 已确认决策

| 项 | 决策 |
|---|---|
| #1 复习交互 | 统一「下一题」前进:三按钮任选→锁定+显示中文→「下一题」;末题置灰 |
| #2 释义范围 | 仅新导入/新建词(走 enrich 路径);老词不动 |
| #2 AI | 部署环境配置 `AI_BASE_URL`、`AI_API_KEY_FILE` 和 `AI_MODEL`;不可用时降级硬截断 |
| #3 txt 词去留 | 沉淀进词库(去重),再用其 ID 生成复习表 |
| #4 复习表模式 | 保留留空回忆(一侧留空),但不画下划线;例句全显示;词+音标同行;音标加 `/ /` |
| #5 学员看结果 | 仅本次复习完即时汇总(页内只读,不加权限) |
| #6 token UI | 完整管理(镜像 CLI:创建/列表/轮换/改 scope/禁用/撤销) |
| #7 备份格式 | SQLite 整库下载(可还原) |

## 2026-07-23 后续增强

1. API 客户端保留“禁用”软停用，并增加管理员永久删除；永久删除级联清理其 token 与 scope，审计记录保留。
2. 单词导入默认采用“更新重复 + AI 补充”；选择“跳过重复”时，在词典和 AI 查询前先检查文件内及数据库重复项，避免无效远程调用。导入窗口可直接查看完整 JSON 字段模板。
3. 复习策略没有任何候选词时返回 `NO_PRACTICE_CANDIDATES`，不创建空会话；列表同时过滤旧版本遗留的零题目会话。
4. 在线复习从按生成时间倒序的最近 3 张有效复习表中选择，自定义标题优先显示；新增 `/api/v1/reviews/today`，仅返回当前登录身份当天已提交的在线复习结果。
5. 打印页改为紧凑蓝色 A4 主题，列宽固定为序号 5%、单词/音标 24%、中文释义 30%、例句 41%，并用 `colgroup` 保证浏览器打印布局一致。

## 默认决定(实现时若需偏离须回头确认)

1. **音标 `/ /` 统一加到所有展示位**:在线复习卡片、复习表、md、pdf 一致(不只用户点名的三处)。
2. **#6 + #7 合并到一个 admin 视图「系统管理」`/system`**:用户管理与复习历史也从系统页进入，主导航只保留一个系统入口。

---

## 组 A — 在线复习 UX(#1 + #5)

### 现状
- `frontend/src/views/ReviewView.vue`:点 `认识/不认识/跳过` → `choose(status)` 调 `PUT .../result` 写结果,置 `revealed=true` 显示中文/例句,聚焦答案区。已有 `next()/previous()` 改 `index`,`finished`(全部已答)显示「查看历史」。
- `components/ResultSelector.vue`:三选项 `known/unknown/skipped`。
- 末题后无汇总;学员无 `reviews:read`,看不到任何结果。

### 改动(纯前端)
- **未答**(`revealed=false`):显示三按钮(不变)。
- **已答**(`revealed=true`):三按钮收起(或置 disabled+高亮所选),下方出现主按钮「下一题」;`index>0` 时同显示「上一题」。
  - 「下一题」绑定现有 `next()`。
  - **末题**(`index === total-1`):「下一题」`disabled`,文案「已完成 ✓」。
- **完成汇总(#5)**:`finished` 时渲染只读汇总面板:
  - 计数:认识 X / 不认识 Y / 跳过 Z。
  - 词表:每词一行 `英文 /音标/ 中文 [状态徽章]`。
  - 数据来自内存 `results`(Map)+ `session.items`;**无新接口、无 `reviews:read`**。
  - admin 额外保留「查看历史」链接(`/history`);学员**不显示**(无权限)。
- 复习卡片的音标用组 C 的 `formatPhonetic` 加斜杠。

### 文件
- 改:`frontend/src/views/ReviewView.vue`、`frontend/src/components/ResultSelector.vue`、`frontend/src/styles/*.css`(按钮区/汇总样式)。

### 测试
- `frontend/tests/unit/review.spec.ts`(新或扩):汇总计数正确、末题「下一题」禁用、答完后按钮区切换。现有 `blankWord` 断言不回归。

---

## 组 B — 词库释义与 txt 选词(#2 + #3)

### #2 释义缩短 + AI 重译(仅 enrich 路径)

#### 现状
- `services/dictionary.py`:`enrich_word()` 从 `dictionary-index.json` 取释义;`shorten_translations(hard_cap=40)` 仅在 `；` 边界截断,加 `…`。
- `services/ai_enrich.py`:OpenAI 兼容 `/chat/completions`,prompt 限制 `cn_meaning ≤ 40` 字;仅在「字典未收录 + `allow_ai`」时触发(`enrich_word` 第 58 行);生产 Key 通过 `AI_API_KEY_FILE` 读取。
- `ai_enabled = bool(ai_base_url and ai_api_key)`。

#### 改动
- **`shorten_translations(translations, *, target=16, min_keep=10)`**:
  1. 清洗 senses(`clean_translation_items`)→ 用 `；` 拼接。
  2. `len ≤ target` → 返回。
  3. 否则在 `[min_keep, target]` 区间找**最后一个**边界符(集合 `。 ； ， , ; . ､`),找到 → 截到该位置并去除尾标点。
  4. **找不到 → 返回 `None`**(信号:截不断,交上层决定)。
- **`enrich_word()`**:拿到字典 `cn_meaning` 后,若 `len > 16`:
  1. 先调严格缩短(同边界逻辑);
  2. 仍过长且 `allow_ai and ai_enabled` → 调 `ai_enrich_word(display)` 取其 `cn_meaning`;
  3. 仍不行 → 最多保留 15 字再加 `…`，总长不超过 16。
  - AI 关闭时自动降级为步骤 3(不报错)。
- **`ai_enrich.py`**:prompt 把 `cn_meaning` 上限 `40 → 16`,并对返回值再跑硬上限兜底(防模型超长)。
- 老词不动(`enrich_word` 只在 create/import 调用)。

#### 文件
- 改:`backend/app/services/dictionary.py`、`backend/app/services/ai_enrich.py`。

#### 测试
- `backend/tests/test_dictionary.py`(新或扩):短释义不变;长释义按 `，/。/；` 截到 ≤16;无边界时 mock `ai_enrich_word` 返回 ≤16 并被采用;AI 关闭时硬截到总长 ≤16(含 `…`)。

### #3 txt 导入选词(沉淀进词库,去重)

#### 现状
- `DailyGenerateView.vue`:自定义选词用 `el-select` 远程搜现有词,填 `form.word_ids`。
- `POST /api/v1/words/import`:支持 txt(每行一词),`conflict_policy=skip` 可跳重复,`unresolved_policy=ai` 让字典外新词自动补释义。
- `POST /api/v1/daily-table/generate`:支持 `word_ids`(必须已入库,保留顺序)。

#### 改动
- **前端 `DailyGenerateView.vue`**:自定义选词区新增「从 txt 导入」面板:
  - `<el-input type="textarea">` + 「解析」按钮。
  - 解析:按换行/逗号/空白拆词 → trim → 去空 → 去重(本地)→ 芯片列表 + 计数。
  - 「导入并生成」:
    1. `POST /api/v1/words/import`(payload=词表,`conflict_policy=skip`,`unresolved_policy=ai`);
    2. 从响应解析出词的 `word_id`(新建 + 已存在);
    3. 填入 `form.word_ids`;
    4. 走现有「生成复习表」(`POST /daily-table/generate`)。
  - 与词库重复:`skip` 去重,生成时只出现一次。
- **接口小补(条件)**:若 `/words/import` 响应不含词的 `word_id`,则最小化扩展响应体,加 `resolved: [{en_word, word_id, action}]`(`action ∈ new|existing|skipped|unresolved`),前端据此填 `word_ids`,避免逐词查询。实现时先验证现有响应再决定是否扩展(若已含 ID 则不改后端)。

#### 文件
- 改:`frontend/src/views/DailyGenerateView.vue`;可能改 `backend/app/api/words.py`(import 响应)+ `frontend/src/api/words.ts`(类型)。

#### 测试
- `backend/tests/test_words_import.py`(扩):import 响应可解析出 ID;用这些 ID 调 generate 成功;`conflict_policy=skip` 重复词只一条。
- 前端单测:txt 解析 + 去重。

---

## 组 C — 复习表 / md / pdf 排版(#4)

### 共享
- 音标格式化器:`formatPhonetic(p) => p ? \`/${p}/\` : ''`。
  - 前端:`frontend/src/utils/formatPhonetic.ts`(新)。
  - 后端:`services/recitation.py` 内同名逻辑。

### 前端 `components/PracticeWorksheet.vue` + `styles/print.css`
- **词+音标同行**:合并「英文」「音标」列为一个单元格,内容 `word /phonetic/`;CSS `.word-cell { white-space: nowrap; }` 强制不换行。
- **留空不画线**:`english()/chinese()` 被回忆侧由 `'________________'` 改为 `''`(空),保留 en-to-cn / cn-to-en 各自留空一侧。
- **例句只显示不填空**:`example()` 不再调 `blankWord()`,直接返回 `example_sentence`。
- 音标加 `/ /`。

### 后端 `services/recitation.py` `build_recitation_md()`
- 表头 `|单词|音标|中文|例句|` → `|单词 /音标/|中文|例句|`;`_cell` 合并 `snapshot_en_word` + `formatPhonetic(snapshot_phonetic)`。
- 例句格已是全句(不动)。

### 文件
- 改:`frontend/src/components/PracticeWorksheet.vue`、`frontend/src/styles/print.css`、`backend/app/services/recitation.py`;新 `frontend/src/utils/formatPhonetic.ts`。
- `frontend/src/utils/blankWord.ts`:若确认组 C 后无其他引用则移除;否则保留(实现时确认)。

### 测试
- `backend/tests/test_recitation.py`(新或扩):md 含 `/phonetic/`、词与音标同格、空音标不出斜杠。
- 前端 `PracticeWorksheet` 组件测试:无下划线、例句全显示、`.word-cell` nowrap class 存在。

---

## 组 D — 管理员工具:API 令牌 + 全量备份(#6 + #7)

### 新 admin 视图「系统管理」`/system`(`meta.roles:["admin"]`,侧栏 icon ⚙),含两个分区。

### #6 API 令牌管理(镜像 CLI)

#### 后端 `app/api/api_clients.py`(新)
- `APIRouter(prefix="/api/v1/api-clients")`,全部 `Depends(require_web_admin)`(角色门禁,**不进 `REQUIRED_SCOPES`**;`ALL_SCOPES` 不变;OpenAPI security 循环跳过本路由)。
- `GET /` — 列表:`[{id, name, description, skill_name, skill_version, status, scopes, tokens:[{id, prefix, state, expires_at, last_used_at}], created_at}]`。**绝不返回 `token_hash`/明文**。
- `POST /` — 创建:body `{name, skill_name, skill_version, scopes[], expires_days?, description?}` → 复用 `core/auth.py:create_api_client_token()` → `201`,响应**一次性**返回 `{...client, token: "wm_..."}`。
- `POST /{id}/tokens` — 轮换:生成新 token,revoke 该 client 旧 token → 返回新明文(一次)。
- `PATCH /{id}` — 改 `{scopes?, description?, status?}`(enable/disable;改 scopes 走 `set_api_client_scopes` 等价逻辑)。
- `DELETE /{id}` — 禁用客户端(`status="disabled"`,保留审计)。
- `DELETE /{id}/tokens/{token_id}` — 撤销单 token(`revoked_at`)。
- 复用 `envelope`/`add_audit`/`_commit`/`AppError`;schemas 加到 `schemas/contracts.py`(`ApiClientCreateRequest` 等,`StrictModel extra="forbid"`)。

#### 前端 `views/SystemView.vue`(令牌分区)
- 客户端表格 + 创建对话框(name/skill_name/skill_version/scopes 多选自 `ALL_SCOPES`/expires_days/description)。
- 创建/轮换后:**明文 token 只弹一次**的对话框——「复制」按钮 + 警示「请立即保存,关闭后不再显示」。
- 行操作:轮换 token / 改 scope / 启用-禁用 / 永久删除客户端 / 撤销 token。
- 新 `frontend/src/api/apiClients.ts`、`types/domain.ts` 加 `ApiClient`/`ApiClientTokenInfo`/payload 类型。

### #7 全量备份(SQLite 整库下载)

#### 后端
- `GET /api/v1/system/backup`,`require_web_admin`:用 SQLite 在线 `backup()` API(复用 `scripts/backup_sqlite.py` 的备份逻辑,提到 `services/backup.py` 或直接内联)写到 `$TMPDIR` 临时文件 → `FileResponse` 流式下载:
  - `media_type="application/octet-stream"`;
  - `Content-Disposition: attachment; filename="vocab-YYYYMMDDHHMMSS.db"`(后端 `datetime`,非 workflow);
  - 发完删临时文件(try/finally)。
  - WAL + backup API 保证写时安全。

#### 前端 `views/SystemView.vue`(备份分区)
- 「下载整库备份」按钮 → 触发浏览器下载(blob,沿用 `apiClient` 的 blob 处理)。
- 说明文字:「该文件可直接用于还原整库(词库 + 复习历史 + 会话等全部数据)。还原:停容器 → 替换 `data/vocab.db` → 起容器。」

#### 文件
- 新:`backend/app/api/api_clients.py`、`backend/app/api/system.py`(或并入 api_clients)、`frontend/src/views/SystemView.vue`、`frontend/src/api/apiClients.ts`。
- 改:`backend/app/main.py`(注册路由 + OpenAPI 跳过)、`backend/app/schemas/contracts.py`、`frontend/src/router/index.ts`(`/system` 路由 + 导航)、`frontend/src/layouts/AppShell.vue`(侧栏过滤)、`frontend/src/types/domain.ts`。

#### 测试
- `backend/tests/test_api_clients_admin.py`(新):admin CRUD 全 200;**学员 session 调 `/api/v1/api-clients/*` → 403**;明文 token 只在创建/轮换响应出现,列表不返回;scopes 校验;未知 scope 报错。
- `backend/tests/test_system_backup.py`(新):`GET /system/backup` → 200 + `Content-Disposition` + 下载内容是合法 sqlite(`PRAGMA integrity_check`);学员 403。

---

## 契约与文档
- `python scripts/export_openapi.py` 重生成 `backend/contracts/openapi.yaml`(新增 `/api/v1/api-clients/*`、`/api/v1/system/backup`;import 响应若有扩展)。
- `CLAUDE.md`:认证/授权段补 `/api/v1/api-clients`(role-gated,不进 `REQUIRED_SCOPES`);词库段补释义 16 字上限 + AI 兜底;新增「全量备份」说明;前端约定补 `/system` 路由。
- `deploy/README.md`:补「数据备份下载」一键操作 + 还原步骤。

---

## 验证(DoD)
- 后端:`cd backend && .venv/bin/pytest -q` 全绿(含 dictionary/AI、import、recitation、api_clients、system_backup);`.venv/bin/ruff check app tests`;`python scripts/export_openapi.py` 后 `git diff --exit-code -- contracts/openapi.yaml`。
- 前端:`npm run typecheck && npm test && npm run build`。
- 本地端到端(已有 `myword-verify` 登录模式实例):
  - admin 建 token(明文只显一次)→ 用该 token 调 `/.well-known/word-review-api` + `/api/v1/words` 通;
  - admin 下载 `.db` 备份,`integrity_check` ok;
  - 复习流:答完显中文→下一题→末题置灰→汇总只读;
  - 导入 txt 生成复习表(含字典外新词经 AI 补释义);
  - 学员复习完看汇总、不能改、不能进 `/system`。
- 生产(NAS):按 `deploy/README.md` 新步骤;备份下载用于更新前备份。

## 实施顺序
A(复习 UX)→ B(释义+txt)→ C(排版)→ D(管理工具)。每组完成后跑该组测试 + 契约检查,可独立提交。
