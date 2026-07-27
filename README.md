# 单词记忆辅助系统

面向个人 NAS 部署的轻量级单词记忆系统。核心理念是 **「纸面为主，网页辅助」**：生成可打印的单词复习表，线下在纸上复习，再回到网页记录每个单词的认识状态，由系统按间隔算法安排后续复习。在线卡片复习作为偶尔使用的辅助入口，与纸面路径共用同一套数据。

同一套响应式网页同时支持手机、平板和电脑。

---

## 它能做什么

系统的主闭环：**词库 → 生成复习表 → 打印纸面复习 → 回网页记录三态 → 历史与统计**。

### 词库管理

- 单词增删改、软删除与恢复；CSV / JSON / 纯英文 TXT 导入；按当前筛选范围导出 CSV / JSON。
- 只输入英文时，自动用本地词典补全音标、中文释义（≤16 字）与例句；词典未命中可由 AI 补全。
- 词库列表直接展示每个词的成功 / 失败次数与上次背诵时间。
- **设为新词**：把已复习过的单词清空复习记录，让它重新作为新词出现、间隔从 1 天重计。

### 复习表生成

- **按策略选词**：默认新词 10、错词 5、到期词 5、自定义词 5；也可指定「总单词数」并按四类权重比例分配。某类不足时自动按 `错词→新词→到期词→自定义词` 顺序补足。
- **自定义选词**：直接挑选一组单词生成，保留选择顺序。
- **从 TXT 导入并生成**：粘贴或选择一份单词文本，导入后直接生成复习表。
- 每张复习表保存策略、随机种子、题目快照与入选原因，**可复现**。

### 复习表会话（纸面主路径）

- 「复习表 / 答案 / 结果回录」三个标签：复习表用于纸面默写，答案用于核对，结果回录用于录入三态。
- **打印**：中英两种留空回忆方向，单词与 `/音标/` 同行、例句全显示、留空侧不画线；标准字号按「约 20 词 / 一页 A4」校准。
- 一键导出 **Markdown / PDF 背诵表**（单词 + 音标 + 中文 + 例句）。
- 每次线下复习创建新轮次，逐项或批量原子保存 `认识 / 不认识 / 跳过`，支持并发冲突处理与失败保留选择。
- 复习表移除后保留复习流水与单词统计；超过 15 天自动归档。

### 在线卡片复习（辅助路径）

- 从最近 3 张复习表中选一张，逐张卡片复习并记录三态，最后一题给出本轮汇总。
- 可查看当前账号今日的复习结果。

### 历史与统计

- 完整复习流水，支持按单词 / 结果 / 来源 / 操作者 / 复习表 / 日期筛选与分页。
- 任意一条记录都可事后纠正，系统在同一事务内重建该词统计。间隔规则 `(1,3,7,14,30)` 天，按连续认识次数推进。

### 系统管理（管理员）

- **数据备份与还原**：一键下载 SQLite 整库快照（词库 + 复习历史 + 会话）；需要时上传 `.db` 备份**还原整库**——还原前系统会先把当前库自动备份为 `pre-restore.db` 并可下载。
- **API 令牌**：为外部 Skill 创建 / 轮换 / 改授权 / 禁用 / 撤销 / 删除令牌；明文 token 仅在创建或轮换时显示一次。
- **用户管理**：创建用户、分配角色、重置口令、启用 / 禁用（带防自锁守卫）。

---

## 角色与权限

- **admin**：全部功能，并可管理用户与系统。
- **student**：只能使用「在线复习」，看不到词库、复习表生成、历史与系统管理。

部署在公网域名时，建议开启登录页（`WEB_LOGIN_REQUIRED=true`），用账号密码登录取代对反向代理的信任。

---

## 备份与还原

在「系统」页：下载整库 `.db` 备份；还原时上传一个 `.db`，系统校验它是本系统的库（关键表与数据库版本一致）后，先自动备份当前库，再原子替换。还原是管理员操作，会覆盖当前全部数据，请谨慎。

---

## 外部 Skill 接入

系统提供带权限的版本化 REST API：外部 Skill 使用 Bearer token（按 scope 授权、幂等、限流、审计），**不能直接访问数据库**。API 发现在 `/.well-known/word-review-api` 与 `/api/v1/capabilities`。

仓库内置四个 Skill：

| Skill | 用途 | 最小 scope |
|---|---|---|
| `add-words` | 预览补全并添加最多 200 个单词，支持手工中文释义 | `words:write` |
| `import-words` | 后台导入 TXT / CSV / JSON 并轮询进度 | `words:write`、`words:read` |
| `generate-worksheet` | 按策略、总词数或指定单词生成复习表 | `practice:generate` |
| `record-review-results` | 读取复习表题目并原子批量回录三态 | `practice:read`、`reviews:write` |

### 安装 Skill

从仓库根目录复制完整 Skill 目录到 Codex 的 Skill 根目录：

```bash
SKILL_ROOT="${CODEX_HOME:-$HOME/.codex}/skills"
mkdir -p "$SKILL_ROOT"
cp -R skills/add-words skills/import-words skills/generate-worksheet skills/record-review-results "$SKILL_ROOT/"
```

重新启动或刷新 Codex 会话后，可通过 `$add-words`、`$import-words`、`$generate-worksheet`、`$record-review-results` 调用。也可先检查脚本是否可见：

```bash
python3 "$SKILL_ROOT/add-words/scripts/add_words.py" --help
```

### 创建并配置 Token

1. 使用管理员账号进入「系统 → API 客户端」，点击「新增客户端」。
2. 填写名称、Skill 名称、版本、有效期，并按上表只选择所需 scope。
3. 创建后立即保存明文 token；关闭弹窗后不能再次查看，只能轮换。
4. 在运行 Skill 的环境中设置：

   ```bash
   export WORD_MEMORY_BASE_URL="https://words.example.com"
   export WORD_MEMORY_API_TOKEN="wm_..."
   ```

   `WORD_MEMORY_BASE_URL` 填站点根地址，**不要**追加 `/api/v1`。生产环境必须使用 HTTPS；脚本仅允许 localhost 使用 HTTP。不要把 token 写入仓库、Compose、提示词或日志。

建议每个 Skill 使用独立客户端和最小权限 token，便于单独撤销、轮换与审计。每个 Skill 的具体输入格式、dry-run、幂等重试和错误处理见其目录内 `SKILL.md`。

---

## 数据与隐私

- 镜像默认**不含** `dictionary-index.json`（体积大、许可证待确认）；需要词库自动补全时，在 NAS 上挂载该文件并设置 `DICTIONARY_INDEX_PATH`。
- AI 补全使用 OpenAI 兼容的 `/chat/completions`；生产环境通过 `AI_API_KEY_FILE` 挂载只读密钥，**不要**把 `AI_API_KEY` 明文写入 Compose 或 Git。

---

## 更多

- **部署 / CI / 镜像发布**：[`deploy/README.md`](./deploy/README.md)（secret 准备、备份、人工更新、健康检查、回滚）。
- **开发约定与架构**：[`CLAUDE.md`](./CLAUDE.md)、[`backend/README.md`](./backend/README.md)、[`frontend/README.md`](./frontend/README.md)。
- **设计文档**：[`docs/design/README.md`](./docs/design/README.md)（架构、数据模型、各阶段设计）。
- **复习表示例**：[`单词背诵表.md`](./单词背诵表.md)。
