# 复习表梅花鹿页头 · TTS 设置补齐 · 概览错词卡片 设计

- 日期：2026-08-24
- 状态：已批准（用户确认素材来源、设置范围、展示条数三项关键决策）
- 关联：`2026-07-24-worksheet-weekday-theme-design.md`（星期主题的前序批次）

## 背景

三个独立需求一次交付：

1. 复习表（worksheet）页头中间空白处按星期显示梅花鹿插图，周一到周日位置从左到右变化，每天只显示一张；
2. TTS 语音参数完全可在系统管理页配置（不依赖 Docker 环境变量预制）；
3. 学员概览页（/dashboard）末尾列出最近的复习错误单词（只读）。

用户已确认的决策：

- 鹿图素材：**手绘 SVG 矢量图**（无法调用 AI 图像生成服务；风格化插画风，非写实渲染）；
- TTS 设置：在现有 base_url / api_key / model / voice 之上**补齐「导入自动生成语音」开关 + 豆包细调参数**；
- 错词列表：**固定 5 个**；错误 = 三态结果 `unknown`；同词去重按最近错误时间；学员只看自己，管理员看全部。

---

## 需求 1：复习表页头梅花鹿（7 张手绘 SVG）

### 素材与组件

- 新建 `frontend/src/components/FawnIllustration.vue`：全仓第二个内联 SVG 组件（先例 `WeekdayDeerIcon.vue`）。
- 单个 `<svg viewBox="0 0 120 90">` 外壳共享背景层（柔和米黄光晕、脚边野花 + 苔藓小点、稀疏光斑），内部 7 组姿势 `<g>` 按 `variant`（`mon…sun`）条件渲染，一天只出现一组。
- 造型要素（Bambi 风格化简笔）：暖金棕皮毛、背部清晰白色梅花斑点、黑色耳尖的大耳朵、有神棕色大眼、奶油色胸腹、细长腿；描边/点缀色引用当日主题 CSS 变量（`--ws-primary/--ws-accent`），跟随现有星期主题换色。
- 姿势表：周一 抬头站定 / 周二 歪头好奇 / 周三 低头嗅花 / 周四 回头望 / 周五 小跳步 / 周六 伸懒腰 / 周日 卧地休息。

### 星期与位置

- `frontend/src/utils/worksheetTheme.ts` 返回值新增 `weekdayIndex`（周一=1 … 周日=7，与 `icon` 同源，仍以 `session.generated_at` 为锚点，改天打印不变）。
- `PracticeWorksheet.vue` 的 `.ws-hero` 增加 `position:relative`，在标题与日期卡之间插入绝对定位 `.ws-fawn`：
  - `left: calc(左界% + (weekdayIndex - 1) / 6 × 可用宽度%)`，周一贴左界、周日贴右界、中间均分；
  - 屏幕高度约 56–64px，不遮挡标题/日期卡（左右界在实现时按实际版面取值并写死注释）。
- 日期卡内现有 34px `WeekdayDeerIcon` 保留不动。

### 打印适配

- `frontend/src/styles/print.css` 补 `.ws-fawn` 打印规则：尺寸按 mm（高约 14mm）、位置公式与屏幕一致、`break-inside:avoid`；`.ws-hero` 现有打印覆盖规则不变，需保证 A4 头部不换行。

### 范围外

- 后端 `/recitation` md/PDF 导出**不加**鹿图（另一界面，后续需求另行处理）。

### 测试

- `practiceWorksheet.spec.ts`：按 `generated_at` 的星期断言渲染对应姿势且仅一张（`.ws-fawn` 单实例 + 变体类名）；位置样式随 `weekdayIndex` 偏移（取周一/周四/周日三点断言 `left` 递增）。
- `worksheetTheme.spec.ts`：补 `weekdayIndex` 7 天映射 + 坏日期回退。
- Playwright `stage4.spec.ts` 打印用例若受 `.ws-hero` 结构影响则同步调整。

---

## 需求 2：TTS 设置补齐（运行时配置，脱离 Docker 预制）

### 决策

沿用现有 `SystemAudioSetting` 单例表 + `PUT /api/v1/system/audio-settings` + 乐观锁 + api_key 掩码机制，只加字段，不新建表/端点。env 继续作为默认值（DB 列为 NULL = 回落 env），现有部署零影响。

### 新增字段（`system_audio_settings` 表，均可空）

| 列 | 类型 | 语义 | 校验边界 |
|---|---|---|---|
| `auto_generate_on_import` | BOOLEAN | 导入单词时自动生成语音（原 `TTS_AUTO_GENERATE_ON_IMPORT`） | 仅 true/false |
| `volc_resource_id` | VARCHAR | 豆包资源 ID（默认 `seed-tts-2.0`） | 非空时 1–64 字符 |
| `volc_speech_rate` | INTEGER | 语速，<0 更慢更平稳（env 默认 -10） | -50…100 |
| `volc_loudness_rate` | INTEGER | 音量，>0 更响更有力（env 默认 20） | 0…100 |
| `volc_silence_ms` | INTEGER | 尾部停顿留白毫秒（env 默认 500） | 0…5000 |

### 后端改动

- 新迁移 `0009_audio_runtime_tuning`：仅 `ALTER TABLE … ADD COLUMN`（遵守已发布迁移铁律），同步 `migrations/released-migrations.sha256.json`，加「从 0008 升级」的真实升级测试。
- `system_settings.audio_runtime_settings()` 覆盖映射新增 5 个键；`_provider_override_values` 支持数值/布尔清洗（str 字段逻辑不变）。
- `update_audio_settings()` 的 setattr 落库扩展到新字段；保存后校验逻辑不变。
- `schemas/contracts.py`：`AudioProviderSettingsUpdate` 增加可选 `resource_id / speech_rate / loudness_rate / silence_ms`（仅 volc 消费，mimo 忽略）；`SystemAudioSettingsUpdate` 增加可选 `auto_generate_on_import: bool`。GET 响应原样返回非密字段与开关状态，api_key 仍只回掩码。
- 消费方切换：`import_worker` 的自动入队判断从 `get_settings().tts_auto_generate_on_import` 改为 `audio_runtime_settings()`（与 `generate_word_audio` 同源）。
- 审计 metadata 不含任何密钥值。

### 前端改动

`SystemView.vue`「本地词库语音」区块：新增「导入时自动生成语音」开关；豆包组新增 4 个细调输入（resource ID / 语速 / 音量 / 尾部停顿 ms，placeholder 显示当前生效值）；保存走现有 `persistAudioSettings`。

### 测试与契约

- `test_system_backup.py` / 新测试：新字段 PUT→GET 回读、边界校验 422、`audio_runtime_settings` 覆盖生效、开关影响 import 入队（mock TTS）。
- 重导出 `backend/contracts/openapi.yaml`（CI 漂移门禁）。

---

## 需求 3：概览页最近 5 个错误单词

### 端点

`GET /api/v1/stats/my-recent-errors`：

- scope：`practice:read` + `reviews:write`（与 `/reviews/today`、`/stats/my-summary` 一致，学员现有权限直接可调，`ALL_SCOPES` 不变）；
- 权限语义：非 admin 按当前 actor（`actor_type/actor_id`）隔离，admin 看全部（复用 `/reviews/today` 的隔离实现）；
- `main.py REQUIRED_SCOPES` 加条目，重导出契约。

### 查询与响应

- 数据源：`ReviewLog`，`status == 'unknown'`，`ORDER BY reviewed_at DESC, id DESC`（命中 `ix_reviews_status_time` / `ix_reviews_actor_time`），学员加 actor 过滤；
- 去重：按 `word_id` 取最新一条，最多 5 个（先取最近 200 条 unknown 日志内存去重截断，规模下单查询足够）；
- 关联 `Word`（软删词仍显示，历史就是历史）带出 `en_word / phonetic / cn_meaning`；
- 响应：`{ items: [ { word_id, en_word, phonetic, cn_meaning, reviewed_at } ] }`（envelope 包装），不足 5 时返回实际数量。

### 前端

`DashboardView.vue` 底部新增「最近错误单词」卡片（admin 与 student 都显示）：每行 单词 + `/音标/`（复用 `formatPhonetic`）+ 中文释义 + 错误时间，纯展示无操作；`src/api/stats.ts` 加 `getRecentErrors()`。

### 测试

- 后端：学员隔离、仅 unknown、去重（同词多次错误一条）、倒序、限 5、词形完整、admin 看全部。
- e2e `stage3.spec.ts` mock 补该路由 + 断言卡片渲染。

---

## 交付计划

1. 实现顺序：需求 2（后端重）→ 需求 3 → 需求 1（纯前端）；
2. 每个需求独立提交；本地门禁：`ruff check` + `pytest` + `typecheck` + `vitest` + `npm run build` + OpenAPI 重导出；
3. 全部通过后 `./scripts/push-and-monitor-actions.sh` 推送，等待 CI（含契约漂移检查、镜像构建、Trivy 扫描）通过。
