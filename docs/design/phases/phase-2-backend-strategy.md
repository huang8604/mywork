# 单词记忆辅助系统－阶段二详细设计

> 实施状态：已完成（2026-07-20）  
> 实现目录：[backend](../../../backend/README.md)  
> 验证：Python 3.12、Alembic 空库升级、15 项 pytest、OpenAPI 导出

## 1. 阶段目标

实现阶段一冻结的 OpenAPI 契约，完成 SQLite 持久化、单词管理、复习三态记录与修改、统计、历史、单词复习表生成策略以及健康检查。

## 2. 后端工程结构

```text
backend/
├── main.py
├── pyproject.toml
├── alembic.ini
├── migrations/
├── app/
│   ├── api/v1/
│   │   ├── words.py
│   │   ├── reviews.py
│   │   ├── stats.py
│   │   ├── practice_sessions.py
│   │   ├── capabilities.py
│   │   └── health.py
│   ├── core/
│   │   ├── config.py
│   │   ├── database.py
│   │   ├── logging.py
│   │   ├── auth.py
│   │   └── exceptions.py
│   ├── models/
│   │   ├── word.py
│   │   ├── review_log.py
│   │   ├── word_stats.py
│   │   ├── practice_session.py
│   │   ├── api_client.py
│   │   └── idempotency_record.py
│   ├── schemas/
│   ├── repositories/
│   └── services/
│       ├── review_service.py
│       ├── stats_service.py
│       ├── strategy_engine.py
│       └── import_export_service.py
├── scripts/
│   ├── rebuild_stats.py
│   ├── create_api_client.py
│   ├── revoke_api_client.py
│   └── backup_sqlite.py
└── tests/
```

采用清晰的 API → service → repository 分层即可，不为小型单用户系统引入额外的抽象层。业务事务由 service 管理，路由不得直接拼装跨表更新。

## 3. 配置、数据库和生命周期

### 3.1 配置

配置从环境变量读取并在启动时校验：

- `DATABASE_URL`，生产默认 `sqlite:////app/data/vocab.db`；
- `APP_TIMEZONE`，默认 `Asia/Shanghai`，仅用于展示和“今日”边界；
- `CORS_ORIGINS`，生产必须为明确的 HTTPS 域名列表；
- `MAX_IMPORT_BYTES`、`MAX_IMPORT_ROWS`、`MAX_PRACTICE_WORDS`；
- `LOG_LEVEL`、`TRUSTED_HOSTS`；
- `PUBLIC_BASE_URL`，用于生成 Skill 可打开的网页和打印 URL；
- `API_TOKEN_PEPPER_FILE`，只读 Secret 文件路径；
- `DICTIONARY_INDEX_PATH`，本地词典索引路径；
- `AI_BASE_URL`、`AI_MODEL`，以及优先使用的 `AI_API_KEY_FILE`（兼容 `AI_API_KEY`），用于本地词典未命中时的 OpenAI-compatible 补全；
- `API_RATE_LIMIT_PER_MINUTE`、`IDEMPOTENCY_RETENTION_DAYS`、`MAX_BATCH_RESULTS`。

同源单容器生产环境通常不需要宽泛 CORS。禁止以 `*` 作为生产 Origins、Methods 和 Headers；仅开放前端实际需要的方法和请求头。

### 3.2 外部 Skill 认证与授权

- API Token 使用至少 256 位随机值，通过本地管理脚本创建，只展示一次；数据库仅保存 Token 前缀和 Argon2id（结合服务端 pepper）摘要，校验使用恒时比较并对连续认证失败限速。
- API 客户端身份与 Token 分表保存。Token 支持列出、到期和立即撤销；轮换时先创建短期并行有效的新 Token，确认 Skill 切换后撤销旧 Token，重叠窗口最多 10 分钟。创建、轮换和撤销均为事务操作。
- Bearer Token 认证后把 `api_client_id` 与 scopes 注入请求上下文，service 根据接口要求再次校验。
- 按 `api_client_id + 客户端 IP` 限流，超过限制返回 `429` 和 `Retry-After`。
- `request_id` 由服务端生成；只接受符合格式的上游 request ID，不能把未校验的客户端值直接写入审计。
- 审计记录 request_id、api_client_id、Skill 名称/版本、作用域、动作、目标 ID、结果和耗时，不记录 Token、完整单词内容或请求正文。Token 创建、轮换、撤销、到期和 scope 变更还需记录管理员、目标客户端、时间和结果。
- 外部 Skill 只能访问白名单业务接口；不提供任意 SQL、Shell、文件路径或任意 URL 请求能力。
- 单用户模式下，`practice:read` 可读取全部复习表，`reviews:write` 可为任意复习表创建新 round 和结果；但修改既有流水仅允许其创建者或网页管理员，所有 repository 查询显式执行该策略。

### 3.3 SQLite 初始化

每个连接启用：

```sql
PRAGMA foreign_keys = ON;
PRAGMA journal_mode = WAL;
PRAGMA busy_timeout = 5000;
```

- 所有写事务保持短小；遇到锁竞争做有限次数退避重试。
- 使用 Alembic 等版本化迁移；迁移失败时 readiness 不通过且应用不接收业务请求。
- `Base.metadata.create_all` 只允许测试或本地空库使用，不承担生产升级。
- 发布前执行 SQLite 一致性备份并校验；提供从备份恢复和从 `review_logs` 重建 `word_stats` 的脚本。

### 3.4 健康与日志

- `GET /healthz/live`：只检查进程存活。
- `GET /healthz/ready`：轻量检查迁移版本和数据库可读。
- 每个请求生成或透传 `request_id`；结构化日志记录路径、状态码、耗时和异常，不记录完整导入内容。
- `/.well-known/word-review-api` 和 `/healthz/live` 可免认证但只返回非敏感信息；`/api/v1/capabilities`、readiness 和业务数据接口需要认证或受信任的内部访问。

## 4. 单词 CRUD 与导入导出

### 4.1 CRUD

- 保存前统一 `en_word` 的空白和大小写规范，依靠唯一约束解决并发重复。
- 查询参数和排序字段通过枚举白名单构造，不直接使用客户端列名。
- 默认稳定排序为 `created_at DESC, id DESC`，分页大小最大 100。
- 删除使用软删除；若单词已在历史中出现，不移除流水和快照。

### 4.2 导入

1. 校验文件大小、扩展名、MIME、UTF-8/BOM 和行数。
2. CSV 使用 `csv.DictReader`，JSON 只接受约定 schema 的数组。
3. 完整解析为 DTO，并按行返回字段错误。
4. 根据 `skip|update|reject` 冲突策略执行单事务批量写入。
5. 成功返回 `created/updated/skipped/rejected/total`，原子成功时 `rejected=0`；失败返回带行号的错误 details 且零写入。重复导入结果可预测。

不得以 `db.merge()` 代替明确的业务冲突策略。

### 4.3 导出

- 复用查询过滤条件，分批读取并流式输出 CSV 或 JSON。
- CSV 固定为带 BOM 的 UTF-8；对以 `=,+,-,@` 开头的单元格做电子表格公式防护。
- 文件响应不经过 JSON envelope。

## 5. 复习三态、修改与统计

### 5.1 提交

`POST /api/v1/reviews` 在单个事务中：

1. 校验单词、可选会话题目和复习轮次；
2. 首次创建时依据 `(actor_type, actor_id, client_event_id)` 唯一约束防止重复事件；HTTP 重试另由 `Idempotency-Key` 处理；
3. 插入 `review_logs`；
4. 原子 UPSERT `word_stats`；
5. 更新关联题目的 `latest_review_log_id`、本轮进度和会话进度；
6. 提交后返回流水和最新统计。

`skipped` 增加跳过次数，但不改变连续认识/不认识、复习间隔和 `due_at`。

### 5.2 手动修改

`PATCH /api/v1/reviews/{id}` 和复习轮次题目结果接口使用相同的 `review_service`：

- 允许在 `known / unknown / skipped` 间直接修改；
- 修改时间写入 `updated_at`；
- 在同一事务内从该单词的有效流水重算统计，避免增量反向计算出错；
- 并发版本冲突返回 `409`，前端展示最新值后由用户决定是否覆盖；
- 修改失败不改变页面当前结果，允许重试。

首次结果创建新的 `client_event_id`；同一轮纠错必须使用原 `client_event_id` 和 `expected_version`。服务端通过 round/item 定位原流水并更新，不能把纠错误判为新一次复习。

同一张打印复习表被再次使用时，先创建新的 `practice_review_round`，再写入一组新的 `review_logs`；不能通过修改上一轮流水来代表一次新的复习。

### 5.3 外部 Skill 批量回录

`PUT /api/v1/practice-review-rounds/{round_id}/results` 复用同一个 `review_service`：

- 最多接收 `MAX_BATCH_RESULTS` 项，MVP 固定为全有或全无的单事务；
- 先校验 Token 的 `reviews:write`、round、全部 item、三态枚举、重复 item 和 `client_event_id`，再开始写入；
- 任一项非法时返回 `422` 且不产生任何流水或统计变更；
- 相同 API 客户端、`Idempotency-Key` 和请求摘要的重试返回首次响应；幂等记录通过业务资源引用重建响应，或短期保存不进入日志的响应 JSON。相同键但不同请求返回 `409 IDEMPOTENCY_KEY_REUSE`；
- 响应包含 round 进度、每项 `review_log_id` 和最新统计摘要。

### 5.4 简单间隔规则

首版采用可解释规则：

- `unknown`：`consecutive_unknown + 1`，连续认识清零，`interval_days=1`；
- `known`：连续认识增加，间隔按 `1 → 3 → 7 → 14 → 30` 天递增；
- `skipped`：不改变间隔；
- `due_at = reviewed_at + interval_days`。

该规则封装在纯函数中并写单元测试，未来可替换为 SM-2/FSRS，但首版不引入复杂模型。

## 6. 单词复习表生成策略

### 6.1 请求校验

```python
class StrategyRequest(BaseModel):
    new_words_limit: int = Field(10, ge=0, le=100)
    error_words_limit: int = Field(5, ge=0, le=100)
    due_words_limit: int = Field(5, ge=0, le=100)
    custom_words_limit: int = Field(5, ge=0, le=100)
    total_words: int | None = Field(None, ge=1)
    fallback_unreviewed_days: int = Field(3, ge=1, le=365)
    seed: int | None = None
```

未设置 `total_words` 时，四类数量总和不得超过配置的 `MAX_PRACTICE_WORDS`。设置后，四类数量作为比例权重，使用最大余数法分配为总和等于 `total_words` 的整数配额；同余数按 `error → new → due → custom` 裁决。权重不能全为 0，且总数模式与 `word_ids` 自选模式互斥。

### 6.2 候选与排序

- 新词：使用 `NOT EXISTS(review_logs)`，可按标签过滤，默认在旧未学词和新导入词之间稳定轮转。
- 错词：候选需有 `unknown_count > 0`；评分综合近期不认识、`consecutive_unknown`、错误率和距上次失败时间。
- 到期词：`due_at <= now`；对旧数据缺少 `due_at` 时才使用 `fallback_unreviewed_days`。
- 自定义词：`is_custom=true`，仍遵循软删除和去重。

每类先取得候选池，再按 `error → new → due → custom` 优先级选取。发生重叠时为单词合并所有 `source_categories`；某类数量不足时，缺额顺延到下一类补足，直到无候选或达到总上限。

### 6.3 可复现与持久化

- 请求未给 seed 时由服务端生成并返回。
- 使用局部随机数生成器打乱，不能修改进程全局随机状态。
- 在同一事务中保存 `practice_sessions` 与快照题目。
- 返回 requested/actual counts、seed、来源、入选原因，以及基于 `PUBLIC_BASE_URL` 的 `web_url` 和 `print_url`。
- 外部 Skill 生成请求要求 `practice:generate` 和 `Idempotency-Key`；相同客户端、键和请求不得创建第二个 session。

## 7. 外部 Skill 接入实现

- `GET /.well-known/word-review-api` 是静态发现文档；`GET /api/v1/capabilities` 从实际配置生成状态枚举、限制和功能开关。
- 网页和外部 Skill 调用相同的 `strategy_engine`、`review_service` 和 repository，不维护第二套自动化业务逻辑。
- OpenAPI 明确 Bearer security scheme、每个操作所需 scope、幂等头、错误码和请求/响应示例。
- API v1 只做兼容性增加；breaking change 使用 v2。弃用信息通过文档和 `Deprecation`/`Sunset` 响应头发布。
- 外部 Skill 的名称和版本来自 `api_clients` 服务端记录，不能完全信任请求体自报字段。

## 8. 测试策略

- 单元测试：规范化、间隔规则、错词评分、去重补位、参数边界、例外日期。
- 数据库测试：外键、软删除、迁移、唯一约束、三态统计、重建统计。
- API 集成测试：CRUD、分页、CSV/JSON、幂等提交、结果修改、历史和 Dashboard。
- 并发测试：相同事件重试、不同事件同时提交、SQLite 锁重试。
- 安全测试：上传限额、危险 CSV 单元格、非法排序字段、CORS 配置。
- Skill 契约测试：发现、OpenAPI、capabilities、scope 允许/拒绝、Token 撤销/过期、生成幂等和批量结果原子性。
- Skill 端到端：生成复习表 → 创建轮次 → 批量提交三态 → 修正本轮结果 → 校验历史和统计。

## 9. Definition of Done

- 空库和上一版本数据库均可迁移启动，外键/WAL/busy timeout 生效。
- 三态提交、重复请求和手工修改后的流水及统计一致。
- 策略满足配额、去重、补位、可复现和来源解释。
- Dashboard、历史、复习表会话接口全部符合阶段一 OpenAPI。
- CSV/JSON 导入的混合错误带行号，导出可重新导入。
- 测试覆盖关键事务与策略；`/healthz/live`、`/healthz/ready` 可用。
- 外部 Skill Token 可创建、最小授权、轮换和撤销；日志可追溯但不泄露凭据。
- 生成与批量回录 Skill 在超时重试后不产生重复 session、round、流水或统计。
