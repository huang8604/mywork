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

1. 使用仓库脚本 push 并等待对应提交的 GitHub Actions 完成：
   ```bash
   ./scripts/push-and-monitor-actions.sh
   ```
   脚本默认先执行 `git push`，等待 60 秒，然后按完整 commit SHA 查找 `ci.yml` 的 push run，并持续轮询到成功或失败；失败或 30 分钟超时会返回非零状态。需要向 `git push` 传参时放在 `--` 后，例如 `./scripts/push-and-monitor-actions.sh -- --set-upstream origin main`。只监控已经 push 的提交时使用 `--skip-push --sha <commit>`。
2. 确认目标提交的测试与镜像发布**成功**,记录对应 `sha-<commit>`。
3. **更新前备份**(见 §2)。
4. 进入 Portainer 的 `vocab-app` 容器/服务。
5. 手动 Pull 目标镜像。日常更新可用 `latest`；变更窗口和回滚应改为已记录的 `sha-<commit>`。
6. 手动 Recreate(沿用原环境变量与数据卷)。
7. 等待容器变为 `healthy`,访问 `/healthz/ready`(应返回 `{"status":"ready"}`)。
8. Smoke:
   - 浏览器登录首页正常;
   - 用专用**只读 Token** 调 `/api/v1/capabilities` 返回正常;
   - (完整 Skill 生成/回录流程已在 CI 临时库中验证,**勿**在生产库跑生成/回录测试以免污染数据。)
9. 记录实际运行 SHA、更新时间、操作者。

### 词典与 AI smoke

导入英文 TXT/文本列表时，本地 `dictionary-index.json` 优先；只有本地未命中的词才调用 AI。导入页面默认选择「AI 补充」。部署后建议用一个明确未收录词执行“仅校验”导入，预期 `dictionary_matches=0`、`unresolved=0` 且预测 `created=1`，然后再执行正式导入。

若未命中词仍被跳过，依次检查：

1. 容器挂载了 `/run/secrets/ai-api-key`，文件非空且 UID 10001 可读；
2. `AI_BASE_URL` 已包含兼容服务的 `/v1`，`AI_MODEL` 存在；
3. `AI_API_KEY_FILE=/run/secrets/ai-api-key` 已生效，未同时依赖明文 `AI_API_KEY`；
4. 容器日志中的 `ai_enrich_failed`（日志不会输出 Key）；
5. 导入请求的未命中策略为 `ai`，而不是 `skip` 或 `reject`。

### 云 TTS smoke

启用 TTS 后，系统页分别保存豆包和 Mimo 的 API URL/Key（Key 只写入服务端，页面只显示掩码），模型与音色沿用服务端默认值。默认使用豆包，调用失败时当前请求自动回退到 Mimo；回退不会改变下次运行的默认服务。

推荐 Stack 环境变量（Key 一律走 secret 文件，不写明文）：

```yaml
TTS_BASE_URL: "https://api.xiaomimimo.com/v1"
TTS_API_KEY_FILE: "/run/secrets/tts-api-key"
TTS_MODEL: "mimo-v2.5-tts"
TTS_VOICE: "Chloe"
VOLC_TTS_BASE_URL: "https://openspeech.bytedance.com"
VOLC_TTS_API_KEY_FILE: "/run/secrets/volc-tts-api-key"
VOLC_TTS_MODEL: "doubao-seed-tts-2.0"
VOLC_TTS_RESOURCE_ID: "seed-tts-2.0"
VOLC_TTS_VOICE: "zh_female_yingyujiaoxue_uranus_bigtts"
TTS_AUTO_GENERATE_ON_IMPORT: "true"
# 可选：TTS_AUDIO_DIR=/app/data/audio、TTS_TIMEOUT_SECONDS=60、VOLC_TTS_TIMEOUT_SECONDS=60
```

部署后 smoke：管理员打开系统设置，确认豆包 URL 默认为 `https://openspeech.bytedance.com`、Mimo URL 为 `/v1` 根地址，分别填写 Key 后点击「测试语音」；服务端会为豆包追加固定的 `/api/v3/plan/tts/unidirectional` 接口。词库页选一个无音频的词 → 点「生成音频」→ 状态变「已生成」并显示实际 provider/model/voice → 点「播放」应能听到 MP3。点「按当前服务重新生成」可在需要时重做整套词库音频；把复习表设为“进行中”后进入 `/review` 在线默写，英文优先播词库 MP3，缺失/失败自动回退浏览器 `speechSynthesis`。

若生成失败，依次检查：

1. 豆包默认 URL 是 `https://openspeech.bytedance.com`，服务端调用其固定的 `/api/v3/plan/tts/unidirectional?api_key=...` 接口；Mimo 使用 `/v1` 根地址并由服务端追加 `/chat/completions`。管理员也可以填写完整豆包 endpoint，服务端会识别并避免重复追加；
2. 两个 API Key 分别保存且服务端日志中的配置检查通过（日志不会输出 Key）；
3. `/app/data/audio`（或 `TTS_AUDIO_DIR`）归 UID 10001 可写；
4. 容器日志中的 `TTS_PROVIDER_ERROR` / `AUDIO_STORAGE_ERROR`（日志不会输出 Key），并检查音频结果上记录的实际 provider/model/voice。

---

### Seed Audio 1.0（0012）

系统管理 → 本地词库语音导入 → 语音服务，选择 `Seed Audio 1.0（seed-audio-1.0）`。
每家服务的「默认语音模型」与「音色」均可下拉选择默认值，也可输入服务支持的自定义模型名称和音色 ID。
填写该服务独立的 API Key，点击「保存设置」后再点「测试语音」或启动词库生成；
Key 留空保留原值，模型、音色和默认服务会持久保存。模型或音色留空则恢复部署默认值。
选择并保存后也会成为单词音频生成的默认服务；已有共享缓存仍会复用，需替换时点击「按当前服务重新生成」。

此服务使用 `POST https://openspeech.bytedance.com/api/v3/tts/create`、`X-Api-Key` 请求头，
与原豆包 agent-plan 接口及 Key 分开配置。按提示词生成中英文朗读，返回 MP3。
它仅在明确选中时调用，不参与豆包/Mimo 的自动备用，也不在失败后换用其他模型。
HTTP 401/403 会显示鉴权或资源权限不足；需要在火山控制台开通相应音频生成资源。
接口与参数依据：[火山音频生成 HTTP 文档](https://docs.volcengine.com/docs/doubao-voice/audio-generation-http?lang=zh)。

也可由部署环境提供默认配置（系统页保存的配置优先）：

```yaml
SEED_AUDIO_BASE_URL: "https://openspeech.bytedance.com"
SEED_AUDIO_API_KEY_FILE: "/run/secrets/seed-audio-api-key"
SEED_AUDIO_TIMEOUT_SECONDS: "300"
SEED_AUDIO_MODEL: "seed-audio-1.0"
# 可选：SEED_AUDIO_VOICE 为参考音色 ID；不设置时由提示词控制音色
```

使用文件方式时需另行挂载对应 secret。升级后入口脚本自动迁移到 `0012`，保留原有两家服务配置。
原豆包连接的默认模型名称 `doubao-seed-tts-2.0` 沿用原接口默认行为；输入其他模型 ID 后会通过 `req_params.model` 提交，需与该服务的资源及音色匹配。
2026-11-04 本机短文本实测：测试凭据返回 HTTP 403 / `45000030` / `requested resource not granted`，
未生成音频；接口可达不能视为模型合成成功。测试凭据未保存在仓库或部署配置中。

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
- 记录当前运行镜像 SHA 与数据库 schema 版本（`SELECT version_num FROM alembic_version`，当前应为 `0012`）。
- 定期在临时目录恢复一份备份,用同版本镜像起一个临时容器,验证单词数、流水数与 `word_stats` 重建一致性(恢复演练)。建议 RPO/RTO 至少做到「更新前备份 + 周期备份」。

---

## 3. 回滚(§7)

1. 在 Portainer 把镜像改为上一个已知正常的 `sha-<commit>`(**不要**依赖漂移的 `latest`)。
2. 检查数据库迁移兼容性:若新版本曾做过破坏性迁移(破坏性迁移本应拆成向前兼容的多步发布),先停容器并从更新前备份恢复。
   已发布的 `backend/migrations/versions/*.py` 禁止删除、重编号或改写；只能新增更高 revision。CI 会按 `backend/migrations/released-migrations.sha256.json` 校验历史迁移哈希和单链关系。
3. Recreate,等待 `healthy`,跑 §1.7 的 smoke。
4. 记录失败版本、原因、恢复结果。

---

## 4. 安全要点

- 容器以非 root(UID/GID 10001)运行,`cap_drop: ALL`、`no-new-privileges`。
- Lucky 负责 HTTPS、访问认证、限流；仅信任实际反代网段传入的 `X-Forwarded-*`，代理应删除客户端伪造的同名头。
- 外部 Skill 必须经 HTTPS 反代访问 API,由应用自身验证 Bearer Token + scope;**服务端到服务端不适用 CORS,不要把 CORS 当认证**。
- token pepper 与 AI Key 文件仅运行 UID 可读；各 Skill 明文 Token 只存在对应 Skill 的 Secret 配置中，不写入 Compose / 镜像 / 仓库 / 日志。
- 应用响应已带 `Content-Security-Policy`、`X-Content-Type-Options`、`Referrer-Policy`(见 `app/main.py`)。
- 语音试听通过 Blob URL 播放，CSP 必须包含 `media-src 'self' blob:`；缺失时所有服务都可能报 `Failed to load because no supported source was found.`。2026-11-04 已用同一份有效 MP3 在 Chromium 复现：原策略拒绝播放，补充该媒体规则后可播放；NAS 实际响应头也确认缺少此规则。

### 已知接受的漏洞风险(`.trivyignore`)

当前 `.trivyignore` 没有活动的漏洞抑制条目。新增抑制必须记录理由；修复版本进入 `requirements.lock` 后应移除对应条目。

2026-11-04，Actions 运行 `41819915805` 的后端、前端、接口契约、镜像构建与启动检查通过，
发布被 Trivy 扫描阻挡。按报告升级运行时锁文件中的四项依赖：

| 依赖 | 原版本 | 修复后锁定版本 |
| --- | --- | --- |
| Brotli | 1.2.0 | 1.2.1 |
| certifi | 2026.6.17 | 2026.10.23 |
| Pillow | 12.3.0 | 13.0.0 |
| WeasyPrint | 65.1 | 70.0 |

生产镜像使用 Python 3.12，满足 Pillow 13 的 Python ≥3.11 要求。
旧的 WeasyPrint SSRF 抑制 `CVE-2025-68616`（修复于 68.0）随此次升级移除。
本地已用完整哈希锁文件安装并通过 `pip check`、27 项 PDF/音频/迁移相关测试；
生成的样例 PDF 经文本提取确认包含中文释义、音标与例句。

---

## 5. Web 登录与角色(可选)

默认 Web 身份由反代注入(`X-Forwarded-User`),应用无登录页。若要用**账号密码登录**(公网暴露、多设备访问、或给学生开只读账号),启用 cookie 登录。

**角色**

- **admin**:全部权限,并在「用户管理」页增删用户、改口令、启用/禁用。
- **student**:可查看「概览」并使用「在线复习」(`/review`)，但不显示词库、复习表、历史等管理入口。后端按 scope 自动挡住词库 CRUD、导出、复习表等管理操作(`ROLE_SCOPES` 里 student = `{practice:read, reviews:write}`)，概览统计按本人复习记录隔离。

**启用(Portainer)**:在 `environment` 加(并**撤销**此前为反代方案加的 `command:` 覆盖;Lucky 反代**移除** `X-Forwarded-User` 注入、只保留 HTTPS):

```yaml
WEB_LOGIN_REQUIRED: "true"
WEB_ADMIN_USERNAME: owner            # 可选,默认 admin
WEB_ADMIN_PASSWORD: "<初始口令,≥6 位>"  # 或 WEB_ADMIN_PASSWORD_FILE 挂 secret
# 可选:SESSION_SECRET(_FILE)(默认复用 token pepper)、SESSION_MAX_AGE(默认 7 天)
```

镜像启动会自动跑迁移到当前版本 + `app.bootstrap`(用上面 env 建首个 admin,幂等)。流程:Pull latest → Recreate → 等 healthy → 浏览器开域名跳 `/login` → 初始口令登录 → admin 在「用户管理」新增学生 → 学生登录默认进 `/dashboard`。

**运维**

- 轮换口令:登录后在「用户管理」改密,或 `docker exec vocab-app python /app/scripts/set_web_password.py --username X --password Y --role student`。
- 登录即访问门槛:启用后任何人需登录才能进入;cookie 仅存用户名(签名),role/禁用态每次请求查库,改了即时生效。CSRF 由 `Origin == PUBLIC_BASE_URL` 校验承担,无需额外配置。
- 关掉登录:删除上面 env 并 Recreate,即回到反代/loopback 认证。
