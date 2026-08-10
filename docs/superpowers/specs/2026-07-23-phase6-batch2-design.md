# 阶段六增强 · 批次 2 设计

## 范围（6 项）

1. **复习表/答案打印排版**：默认字号略大，20 个词的「答案」页大约落在一页 A4。
2. **历史复习表卡片词数错误**：自选 10 词卡片显示 20（双计）。
3. **结果回录里 `selected` / `unique_total` 是英文**：相关文案改中文。
4. **词库单词可设为新词**：清空该词复习记录 → 重新进入新词池。
5. **备份 .db 导入（还原整库）**：自动先备份 + 校验 + 原子替换。
6. **README 改为功能导向文档**。

## 已定决策

- #1：重调「标准」档为 20 词/页的甜点字号（略大 + 收紧 padding/行高/例句列）。
- #2/#3：同一根因——`actual_counts` 把总量 `unique_total` 与分类计数混在一起；前端 `count()` 求和双计，且原始 key 渲染为英文。**纯前端修复**。
- #4：清空该词 `ReviewLog` + `WordStats`（destructive，二次确认 + 审计，幂等）。
- #5：上传 .db → 校验 schema → 自动备份当前库到 `data/pre-restore.db` → `engine.dispose()` → 原子 `os.replace` → 仅 admin。
- #6：重写根 README 为功能导向；部署/CI/开发细节下沉到链接。

## 变更点

### A. #2/#3 前端（共享根因）
- 新增 `sessionWordCount(s)`：`actual_counts.unique_total` 优先，否则求和分类键（排除 `unique_total`/`selected`）。
- `DailyGenerateView` 卡片用之（10 而非 20）。
- `PracticeSessionView.countLabels` 加 `selected:'自选'`、`unique_total:'总词数'`；「实际入选」渲染为 `总词数 N` + 分类明细，不再重复。
- 单测：自选会话=10；分类会话求和正确。

### B. #1 打印（`PracticeWorksheet.vue` + `print.css`）
- 重调 medium：body≈11pt / word≈14pt，单元格 padding≈3pt，line-height≈1.2，例句列与例句字号略缩；20 行答案落一页。小/大保留为更小/更大档；默认仍 medium。

### C. #4 设为新词（后端 + 前端）
- `POST /api/v1/words/{id}/reset-progress`（`words:write`，入 `REQUIRED_SCOPES`）：事务内删该词 `ReviewLog` + `WordStats`，写审计，幂等。
- `WordsView`：逐行 + 多选批量「设为新词」，二次确认提示清空复习记录。
- 测试：重置后该词重回新词池、统计归零、审计写入。

### D. #5 还原（后端 + 前端，admin）
- `POST /api/v1/system/restore`（multipart `.db`，`require_web_admin`，不入 `REQUIRED_SCOPES`）：存临时 → 只读校验关键表 + `alembic_version`≤当前 → 自动备份当前库到 `data/pre-restore.db` → `engine.dispose()` → `os.replace` 覆盖（删 `-wal`/`-shm`）→ 返回 `{backed_up_at, bytes}`。失败不替换。
- `GET /api/v1/system/pre-restore-backup`：下载该自动备份（单文件）。
- `SystemView`：「还原数据库」面板，上传 + 强确认 → 成功提示已自动备份可下载。
- 测试：还原替换数据；坏文件拒绝；自动备份生成。

### E. #6 README
- 根 `README.md` 功能导向（中文）：能做什么 → 纸面复习闭环 → 按页面讲功能 → 角色 → 外部 Skill → 「更多」链接 deploy/README 与 CLAUDE.md。

### 收尾
- 重生成 `contracts/openapi.yaml`；删除游离 `package.txt`。

## 验证
- 后端：容器内 `ruff check app tests && pytest -q`（含 reset-progress、restore）。
- 前端：`typecheck && test && build`（含 sessionWordCount 单测）。
- `python scripts/export_openapi.py` 后 `git diff --exit-code -- contracts/openapi.yaml`。
