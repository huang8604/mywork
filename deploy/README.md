# NAS 部署与运维(阶段五)

单容器全栈部署。镜像由 GitHub Actions 在每次 push 到 `main` 时构建并推送到 GHCR:

- `ghcr.io/huang8604/vocab-app:latest` —— 滚动,仅 main 最新成功构建
- `ghcr.io/huang8604/vocab-app:sha-<commit>` —— 不可变,用于审计与回滚

> **发布模型**:运维**人工**在 Portainer 中 Pull + Recreate。**不**配置 Watchtower / Webhook / Portainer API 自动更新。Recreate 是短暂重启,不是「零停机」或「热更新」。

---

## 0. 前置准备(首次部署)

仓库内有两份 Stack 文件：

- `portainer-stack.yml`：当前 `myword.myjojo.fun:666` + Lucky + NAS 路径的实际部署配置，已被 `.gitignore` 排除，只保留在部署工作区；
- `portainer-stack.template.yml`：进入版本控制的安全模板，给其他环境复制使用，部署前必须替换全部 `REPLACE_ME`。

两份文件都只引用 secret 文件，不保存明文 pepper、AI Key 或网页登录口令。

1. 在 GitHub 仓库 Settings → Actions 确认 workflow 可写 GHCR(`GITHUB_TOKEN` 默认有 `packages: write`)。
2. NAS 上预建目录并赋权(镜像内非 root 用户 UID/GID = 10001):
   ```bash
   mkdir -p /share/Container/vocab-app/data /share/Container/vocab-app/secrets
   chown -R 10001:10001 /share/Container/vocab-app/data /share/Container/vocab-app/secrets
   ```
3. 生成 token pepper（≥32 字节）并落盘：
   ```bash
   head -c 64 /dev/urandom > /share/Container/vocab-app/secrets/api-token-pepper
   chmod 0400 /share/Container/vocab-app/secrets/api-token-pepper
   chown 10001:10001 /share/Container/vocab-app/secrets/api-token-pepper
   ```
4. 把 AI Key 写入独立 secret 文件。不要把 Key 写进 Stack、shell 历史或 Git：
   ```bash
   umask 077
   read -r -s -p 'AI API Key: ' VOCAB_AI_KEY
   printf '%s' "$VOCAB_AI_KEY" > /share/Container/vocab-app/secrets/ai-api-key
   unset VOCAB_AI_KEY
   chmod 0400 /share/Container/vocab-app/secrets/ai-api-key
   chown 10001:10001 /share/Container/vocab-app/secrets/ai-api-key
   ```
5. 把 TTS Key 写入独立 secret 文件。词库「生成音频」和在线默写云 MP3 都由后端读取此文件，前端不会接触 Key：
   ```bash
   umask 077
   read -r -s -p 'TTS API Key: ' VOCAB_TTS_KEY
   printf '%s' "$VOCAB_TTS_KEY" > /share/Container/vocab-app/secrets/tts-api-key
   unset VOCAB_TTS_KEY
   chmod 0400 /share/Container/vocab-app/secrets/tts-api-key
   chown 10001:10001 /share/Container/vocab-app/secrets/tts-api-key
   ```
6. 将已确认授权的 `dictionary-index.json` 放到 `/share/Container/vocab-app/dictionary-index.json`，并确保 UID 10001 可读。
7. 当前环境直接检查 `portainer-stack.yml`；新环境复制模板并替换全部 `REPLACE_ME`（域名、NAS 根目录、端口、反代 CIDR、模型和不可变镜像标签）。
8. Lucky 上游设为 `http://127.0.0.1:8587`，对外入口为 `https://myword.myjojo.fun:666`。Lucky 必须覆盖 `X-Forwarded-For`、`X-Forwarded-Proto`、`Host`，并删除客户端自带的 `X-Forwarded-User` 后再注入可信网页身份。
9. 在 Portainer Stacks 用目标文件部署。容器端口只绑定 loopback，公网和局域网其他机器不得绕过 Lucky 直连。

### 关键代理配置为什么有两项

- `TRUSTED_PROXY_CIDRS` 由应用鉴权读取，决定哪些来源可提交 `X-Forwarded-User`；
- `FORWARDED_ALLOW_IPS` 由 Uvicorn 读取，决定哪些来源可提交 `X-Forwarded-For` / `X-Forwarded-Proto`。

Docker 端口发布后，Lucky 请求在容器内通常来自 `172.x` 网桥网关，因此当前实际部署同时信任 `172.16.0.0/12`。不要只配置其中一项，也不要在端口对外开放时使用 `*`。

---

## 1. 更新流程(人工)

1. 在 GitHub Actions 确认目标提交的测试与镜像发布**成功**,记录对应 `sha-<commit>`。
2. **更新前备份**(见 §2)。
3. 进入 Portainer 的 `vocab-app` 容器/服务。
4. 手动 Pull 目标镜像。日常更新可用 `latest`；变更窗口和回滚应改为已记录的 `sha-<commit>`。
5. 手动 Recreate(沿用原环境变量与数据卷)。
6. 等待容器变为 `healthy`,访问 `/healthz/ready`(应返回 `{"status":"ready"}`)。
7. Smoke:
   - 浏览器登录首页正常;
   - 用专用**只读 Token** 调 `/api/v1/capabilities` 返回正常;
   - (完整 Skill 生成/回录流程已在 CI 临时库中验证,**勿**在生产库跑生成/回录测试以免污染数据。)
8. 记录实际运行 SHA、更新时间、操作者。

### 词典与 AI smoke

导入英文 TXT/文本列表时，本地 `dictionary-index.json` 优先；只有本地未命中的词才调用 AI。导入页面默认选择「AI 补充」。部署后建议用一个明确未收录词执行“仅校验”导入，预期 `dictionary_matches=0`、`unresolved=0` 且预测 `created=1`，然后再执行正式导入。

若未命中词仍被跳过，依次检查：

1. 容器挂载了 `/run/secrets/ai-api-key`，文件非空且 UID 10001 可读；
2. `AI_BASE_URL` 已包含兼容服务的 `/v1`，`AI_MODEL` 存在；
3. `AI_API_KEY_FILE=/run/secrets/ai-api-key` 已生效，未同时依赖明文 `AI_API_KEY`；
4. 容器日志中的 `ai_enrich_failed`（日志不会输出 Key）；
5. 导入请求的未命中策略为 `ai`，而不是 `skip` 或 `reject`。

### 云 TTS smoke

启用 TTS 后，词库页会显示每个词的音频状态。部署后选一个无音频的普通词，点「生成音频」→ 状态变为「已生成」→ 点「播放」应能听到 MP3；进入 `/review` 的「在线默写」时会优先播放该 MP3，未生成或播放失败时自动回退浏览器 `speechSynthesis`。

推荐 Stack 环境变量（Key 走 secret 文件，不写明文）：

```yaml
TTS_BASE_URL: "https://api.xiaomimimo.com/v1"
TTS_API_KEY_FILE: "/run/secrets/tts-api-key"
TTS_MODEL: "mimo-v2.5-tts"
TTS_VOICE: "Chloe"
# 可选:TTS_AUDIO_DIR=/app/data/audio、TTS_TIMEOUT_SECONDS=60
```

若生成失败，依次检查：

1. 容器挂载了 `/run/secrets/tts-api-key`，文件非空且 UID 10001 可读；
2. `TTS_API_KEY_FILE` 已生效，未把 Key 写入明文环境变量；
3. `TTS_BASE_URL` 包含 `/v1`，模型为 `mimo-v2.5-tts`，voice 为已验证的 `Chloe`；
4. `/app/data/audio`（或 `TTS_AUDIO_DIR`）归 UID 10001 可写；
5. 容器日志中的 `TTS_PROVIDER_ERROR` / `AUDIO_STORAGE_ERROR`（日志不会输出 Key）。

---

## 2. 备份与校验(§4)

数据库是 `/share/Container/vocab-app/data/vocab.db`(SQLite,WAL 模式,另有 `-shm`/`-wal`)。**挂卷 ≠ 备份。**

### 数据备份下载(Web,推荐)

admin 登录后进入 **系统管理 → 数据备份**,点「下载整库备份(.db)」即可一键拿到当时的整库 `.db` 快照(走 `GET /api/v1/system/backup`,服务端在线备份后流式下发,与下方 `docker exec` 方式等价)。更新前备份优先用此入口,免 SSH。**恢复**:停容器 → 用下载的 `.db` 替换 `data/vocab.db`(及同名 `-wal`/`-shm`,建议一并删除让 WAL 重建)→ 起容器 → 等 `healthy`。

### 命令行备份(替代)



```bash
# 容器内用 SQLite 在线备份 API(写时安全),产出时间戳副本:
docker exec vocab-app python - <<'PY'
from pathlib import Path
import sqlite3, datetime
src = "/app/data/vocab.db"
dst = f"/app/data/backup/vocab-{datetime.datetime.utcnow():%Y%m%dT%H%M%SZ}.db"
Path(dst).parent.mkdir(parents=True, exist_ok=True)
con = sqlite3.connect(src)
con.backup(sqlite3.connect(dst))
con.close()
print(dst)
PY

# 完整性校验 + 可读性:
docker exec vocab-app python -c "import sqlite3; c=sqlite3.connect('/app/data/vocab.db'); print(c.execute('PRAGMA integrity_check').fetchone())"
```

- 至少保留最近若干版本,并复制到**不同物理存储**。
- 记录当前运行镜像 SHA 与数据库 schema 版本（`SELECT version_num FROM alembic_version`，当前应为 `0004`）。
- 定期在临时目录恢复一份备份,用同版本镜像起一个临时容器,验证单词数、流水数与 `word_stats` 重建一致性(恢复演练)。建议 RPO/RTO 至少做到「更新前备份 + 周期备份」。

---

## 3. 回滚(§7)

1. 在 Portainer 把镜像改为上一个已知正常的 `sha-<commit>`(**不要**依赖漂移的 `latest`)。
2. 检查数据库迁移兼容性:若新版本曾做过破坏性迁移(破坏性迁移本应拆成向前兼容的多步发布),先停容器并从更新前备份恢复。
3. Recreate,等待 `healthy`,跑 §1.7 的 smoke。
4. 记录失败版本、原因、恢复结果。

---

## 4. 安全要点

- 容器以非 root(UID/GID 10001)运行,`cap_drop: ALL`、`no-new-privileges`。
- Lucky 负责 HTTPS、访问认证、限流；仅信任实际反代网段传入的 `X-Forwarded-*`，代理应删除客户端伪造的同名头。
- 外部 Skill 必须经 HTTPS 反代访问 API,由应用自身验证 Bearer Token + scope;**服务端到服务端不适用 CORS,不要把 CORS 当认证**。
- token pepper 与 AI Key 文件仅运行 UID 可读；各 Skill 明文 Token 只存在对应 Skill 的 Secret 配置中，不写入 Compose / 镜像 / 仓库 / 日志。
- 应用响应已带 `Content-Security-Policy`、`X-Content-Type-Options`、`Referrer-Policy`(见 `app/main.py`)。

### 已知接受的漏洞风险(`.trivyignore`)

CI 的 Trivy 门禁扫到、但经评估**在本系统威胁模型下不可利用**、故写入仓库根 `.trivyignore` 显式抑制的条目。每项都必须有理由,并在升级依赖时复核(修复版本一旦进入 `requirements.lock` 就删掉对应行)。

- **CVE-2025-68616**(WeasyPrint SSRF,HIGH;修复于 68.0,当前镜像装 65.1)。该 SSRF 需在渲染内容里塞入 `http(s)://` URL(如 markdown 图片或 CSS `url()`)才会触发服务端抓取;而 `/practice-sessions/{id}/recitation` PDF 渲染的 markdown 来自单词字段(text / cn_meaning / example_sentence),这些字段**仅**认证 web admin(即 owner 本人)或 owner 自己持有 `words:write` 的 API client 可写。无任何匿名/不可信用户能注入,因此不存在可越权的边界 → 实际风险为零。**待办**:待后续 `requirements.lock` 整体升级时一并把 weasyprint 升到 ≥68.0,并删除此条抑制。

---

## 5. Web 登录与角色(可选)

默认 Web 身份由反代注入(`X-Forwarded-User`),应用无登录页。若要用**账号密码登录**(公网暴露、多设备访问、或给学生开只读账号),启用 cookie 登录。

**角色**

- **admin**:全部权限,并在「用户管理」页增删用户、改口令、启用/禁用。
- **student**:只能使用「在线复习」(`/review`)。后端按 scope 自动挡住词库 CRUD、导出、复习表等管理操作(`ROLE_SCOPES` 里 student = `{practice:generate, practice:read, reviews:write}`)。

**启用(Portainer)**:在 `environment` 加(并**撤销**此前为反代方案加的 `command:` 覆盖;Lucky 反代**移除** `X-Forwarded-User` 注入、只保留 HTTPS):

```yaml
WEB_LOGIN_REQUIRED: "true"
WEB_ADMIN_USERNAME: owner            # 可选,默认 admin
WEB_ADMIN_PASSWORD: "<初始口令,≥6 位>"  # 或 WEB_ADMIN_PASSWORD_FILE 挂 secret
# 可选:SESSION_SECRET(_FILE)(默认复用 token pepper)、SESSION_MAX_AGE(默认 7 天)
```

镜像启动会自动跑迁移到当前版本 + `app.bootstrap`(用上面 env 建首个 admin,幂等)。流程:Pull latest → Recreate → 等 healthy → 浏览器开域名跳 `/login` → 初始口令登录 → admin 在「用户管理」新增学生 → 学生登录默认进 `/review`。

**运维**

- 轮换口令:登录后在「用户管理」改密,或 `docker exec vocab-app python /app/scripts/set_web_password.py --username X --password Y --role student`。
- 登录即访问门槛:启用后任何人需登录才能进入;cookie 仅存用户名(签名),role/禁用态每次请求查库,改了即时生效。CSRF 由 `Origin == PUBLIC_BASE_URL` 校验承担,无需额外配置。
- 关掉登录:删除上面 env 并 Recreate,即回到反代/loopback 认证。
