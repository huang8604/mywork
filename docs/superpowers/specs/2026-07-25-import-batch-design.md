# 词库后台导入 + 文本导入标签 + 多选批量操作

## 背景

三个相互独立的词库体验改进,合并一个 spec 实施:

1. **导入超时全量丢失**:`POST /words/import` 当前 `BEGIN IMMEDIATE` → 逐词 `enrich_word`(词典 + AI,可能慢)→ 末尾一次 `_commit`。前端 60s 超时 → 服务端事务回滚 → **一个都没导入**。改为后台 + 单词独立事务 + 进度。
2. **文本导入无法打标签**:`.txt`(每行一个英文)只产出 `{en_word}`,无 tags。加「默认标签」输入,并集到所有行。
3. **词库无批量操作**:逐个点删/改标签很慢。加多选 + 4 个批量动作。

---

## Feature 1 — 后台导入(部分写入 + 进度)

### 问题根因
`/words/import` 单事务 + 末尾 commit,慢 enrichment 拖垮整个事务,超时即全回滚。

### 后端
- 新 `app/services/import_worker.py`(平行 `audio_worker.py`,复用 daemon-thread + 计数器模式):单线程串行处理导入队列;`_ImportJob(payloads, conflict_policy, unresolved_policy, default_tags, actor_type, actor_id, request_id, idempotency_key)`。
- 进度字段:`state/total/processed/created/updated/skipped/failed/unresolved`;完成时填 `resolved`、`unresolved_words`、`audio_generation.queued`、`finished`。
- **逐词独立 session+commit**:每词开新 session → 冲突检查 → `enrich_word`(按 `unresolved_policy`)→ create/update/reimport → commit。任一异常 → rollback + 计 failed/skip + **继续**(不阻断)。进程中断 → 已落库词保留,操作者重触。
- 任务完成:对 `created` 词批量 `enqueue_audio_generation`(沿用现有音频后台;`tts_auto_generate_on_import` + 任一 provider 配置时)。
- `import_progress()` 暴露快照。

### `/import` 路由改写(`app/api/words.py`)
1. 同步:`read` + `_parse_import`(语法错误立即 422)+ `max_import_*` 校验 + 合并 `default_tags`(Feature 2)。
2. `dry_run=true`:**保持同步预览**(无写入,去掉 `BEGIN IMMEDIATE`)。
3. `conflict_policy=reject`:**写入前预扫**(一条 `IN` 查询查已存在非删除词);有冲突 → 立即 409/422,不入队、零写入。
4. 否则:`claim()` 幂等 → 入 `import_worker` 队列 → 立即返回 `{state:"running", total, processed:0, ...}`。
- 新 `GET /api/v1/words/import/progress`(scope `words:read`)。

### 策略语义(后台模式下收敛,符合"部分成功")
- `unresolved_policy` 仅控制**是否尝试 AI**(`ai`→试;`skip`/`reject`→不试)。未命中词永不写入(`create_word` 要求 `cn_meaning`),只计数 + 列出。
- `conflict_policy=reject` 靠预扫保证零写入;`skip`/`update` 在 worker 内逐词处理。

### 幂等
路由 `claim()`(持久化)→ worker 完成 `complete(idem, data=最终汇总)`。replay:已完成 → 返回最终汇总(`Idempotency-Replayed:true`);运行中 → 返回 `{state:"running",...}`。

### 前端
- 「开始导入」(非 dry-run):POST 立即返回 → 关闭对话框 → 顶部「导入后台进行中」面板(复用音频进度轮询:`setInterval` 拉 `/words/import/progress`)。
- 运行中:进度条 `processed/total`,文字 `已新增 X · 已更新 Y · 跳过 Z · 失败 W`。
- 完成(`state=idle`):面板展开汇总(新增/更新/跳过/未命中 + `unresolved_words`)+ 刷新词库 + toast。

---

## Feature 2 — 文本导入默认标签(并集到所有行)

- 导入对话框加「默认标签」输入(逗号分隔,镜像现有筛选标签输入)。
- API:`POST /words/import` 加 Form 字段 `tags: str`(逗号分隔)→ 解析为 `list[str]` → `_parse_import` 每行 `payload.tags` 做**并集合并**(normalize 感知去重保序)。文本/CSV/JSON 全生效。
- 校验:并入后每行受 `WordCreate.tags`(≤20、normalize 唯一)约束;超限 → 该行按错误跳过(Feature 1 容错覆盖)。

---

## Feature 3 — 多选批量操作(删除 / 加标签 / 生成音频 / 设为新词)

### 后端(新批量端点,均 scope `words:write`,逐词乐观锁 + 部分成功,单次 audit)

| 端点 | 入参 | 行为 | 返回 |
|---|---|---|---|
| `POST /words/batch/delete` | `{items:[{id,expected_version}]}` | 逐词 `delete_word` | `{deleted:[{id}], conflicts:[{id,current_version}], missing:[{id}]}` |
| `POST /words/batch/tags` | `{items:[{id,expected_version}], tags:[...]}` | 逐词合并标签(existing ∪ new)+ version+1 | `{updated:[{id,version}], conflicts, missing}` |
| `POST /words/batch/audio` | `{word_ids:[...], provider?}` | `enqueue_audio_generation`(火忘) | `{queued,total,provider}` |
| `POST /words/batch/reset-progress` | `{word_ids:[...]}` | 逐词 `reset_word_progress`(不动 version) | `{reset:N}` |

- 新 service 助手(`services/words.py`):`batch_delete_words`、`batch_add_tags`(内部调新 `_add_tags_to_word(db, word_id, tags, expected_version)` —— 不走全量 `WordUpdate`,直接 `_set_tags` 合并 + version bump)、`batch_reset_progress`。逐词 `try/except AppError(VERSION_CONFLICT)` 收集冲突,不阻断。单事务末尾一次 commit。
- 幂等:批量端点用 `Idempotency-Key` header 整请求防重(claim/complete)。

### 前端
- `ResponsiveWordList.vue`:桌面 `el-table` 加 `type="selection"` 列 + `@selection-change`;移动 `WordCard.vue` 加 checkbox。选中状态由 `WordsView` 持有(`selection-change` 上传 `Word[]`)。
- `WordsView.vue`:选中非空时顶部浮出批量操作栏「已选 N 项」+ 四按钮 +「取消选择」。
  - 删除:确认框 → `batchDeleteWords` → 报告 `已删除 X,冲突 Y`。
  - 加标签:小弹窗输标签 → `batchSetTags` → 报告结果。
  - 生成音频:`batchGenerateAudio` → toast `已加入音频队列 N 个` + 启动音频进度轮询。
  - 设为新词:确认框 → `batchResetProgress` → toast。
  - 完成:刷新列表 + 清空选择。

---

## 文件清单

**后端**
- 新:`app/services/import_worker.py`、`backend/tests/test_import_worker.py`、`backend/tests/test_word_batch.py`
- 改:`app/api/words.py`、`app/services/words.py`、`app/schemas/contracts.py`、`app/main.py`、`contracts/openapi.yaml`(重生成)

**前端**
- 改:`src/api/words.ts`、`src/types/domain.ts`、`src/views/WordsView.vue`、`src/components/ResponsiveWordList.vue`、`src/components/WordCard.vue`

**文档**:`CLAUDE.md`(导入改后台 + 批量端点段落)

## 验证
- 后端:`pytest -q`(新 import_worker + batch)、`ruff check app tests`、`export_openapi.py` + `git diff --exit-code -- contracts/openapi.yaml`。
- 前端:`npm run typecheck && npm test && npm run build`。
- e2e(LAN):大文本导入不再超时、进度可见、部分落库;四项批量动作生效;文本导入带标签。

## 部署 / NAS
Pull latest → Recreate。导入对话框新增「默认标签」;大导入入后台、顶部进度面板;词库支持多选批量。
