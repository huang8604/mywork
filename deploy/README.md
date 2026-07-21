# NAS 部署与运维(阶段五)

单容器全栈部署。镜像由 GitHub Actions 在每次 push 到 `main` 时构建并推送到 GHCR:

- `ghcr.io/huang8604/vocab-app:latest` —— 滚动,仅 main 最新成功构建
- `ghcr.io/huang8604/vocab-app:sha-<commit>` —— 不可变,用于审计与回滚

> **发布模型**:运维**人工**在 Portainer 中 Pull + Recreate。**不**配置 Watchtower / Webhook / Portainer API 自动更新。Recreate 是短暂重启,不是「零停机」或「热更新」。

---

## 0. 前置准备(首次部署)

1. 在 GitHub 仓库 Settings → Actions 确认 workflow 可写 GHCR(`GITHUB_TOKEN` 默认有 `packages: write`)。
2. NAS 上预建目录并赋权(镜像内非 root 用户 UID/GID = 10001):
   ```bash
   mkdir -p /share/Container/vocab-app/data /share/Container/vocab-app/secrets
   chown -R 10001:10001 /share/Container/vocab-app/data /share/Container/vocab-app/secrets
   ```
3. 生成 token pepper(≥32 字节)并落盘:
   ```bash
   head -c 64 /dev/urandom > /share/Container/vocab-app/secrets/api-token-pepper
   chmod 0400 /share/Container/vocab-app/secrets/api-token-pepper
   chown 10001:10001 /share/Container/vocab-app/secrets/api-token-pepper
   ```
4. 编辑 `portainer-stack.yml`,替换所有 `REPLACE_ME`(域名、反代 CIDR);按需挂载 `dictionary-index.json`、AI key。
5. 在 Portainer Stacks 用该文件部署;反向代理负责 HTTPS、访问认证、请求体限制与限流,公网**不得**直连 8080。

---

## 1. 更新流程(人工)

1. 在 GitHub Actions 确认目标提交的测试与镜像发布**成功**,记录对应 `sha-<commit>`。
2. **更新前备份**(见 §2)。
3. 进入 Portainer 的 `vocab-app` 容器/服务。
4. 手动 Pull `ghcr.io/huang8604/vocab-app:latest`。
5. 手动 Recreate(沿用原环境变量与数据卷)。
6. 等待容器变为 `healthy`,访问 `/healthz/ready`(应返回 `{"status":"ready"}`)。
7. Smoke:
   - 浏览器登录首页正常;
   - 用专用**只读 Token** 调 `/api/v1/capabilities` 返回正常;
   - (完整 Skill 生成/回录流程已在 CI 临时库中验证,**勿**在生产库跑生成/回录测试以免污染数据。)
8. 记录实际运行 SHA、更新时间、操作者。

---

## 2. 备份与校验(§4)

数据库是 `/share/Container/vocab-app/data/vocab.db`(SQLite,WAL 模式,另有 `-shm`/`-wal`)。**挂卷 ≠ 备份。**

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
- 记录当前运行镜像 SHA 与数据库 schema 版本(`SELECT version_num FROM alembic_version`,当前应为 `0002`)。
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
- 反向代理负责 HTTPS、访问认证、限流;仅信任实际反代网段传入的 `X-Forwarded-*`,代理应删除客户端伪造的同名头。
- 外部 Skill 必须经 HTTPS 反代访问 API,由应用自身验证 Bearer Token + scope;**服务端到服务端不适用 CORS,不要把 CORS 当认证**。
- token pepper 文件仅运行 UID 可读;各 Skill 明文 Token 只存在对应 Skill 的 Secret 配置中,不写入 Compose / 镜像 / 仓库 / 日志。
- 应用响应已带 `Content-Security-Policy`、`X-Content-Type-Options`、`Referrer-Policy`(见 `app/main.py`)。
