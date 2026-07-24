# Phase 2：云 TTS MP3 + 词库音频管理 + 在线默写优先云音频

## 背景

Phase 1 已在 `/review` 中增加「在线卡片 / 在线默写」切换，并用浏览器 `speechSynthesis` 完成默写播放调度。Phase 2 在此基础上增加服务端云 TTS：由 FastAPI 调用 mimo TTS 生成 MP3，保存到服务端可写数据目录；词库页支持播放、生成、重生成、批量生成；在线默写优先播放服务端 MP3，无音频或播放失败时回退 Phase 1 的浏览器朗读。

已实测 mimo TTS：`https://api.xiaomimimo.com/v1` 可用；`/v1/audio/speech` 不支持；可用形态为 chat-completions，文字放 `assistant` 消息，`audio:{voice:"Chloe",format:"mp3"}`，返回 `choices[0].message.audio.data` base64。MP3 对单词约数 KB。当前只确认 `Chloe` 可用；英音/美音选择仍由浏览器 fallback 承担。

## 目标

- admin 能在词库里为单词生成/重生成 MP3，并播放已生成音频。
- admin 能一键按词库顺序批量生成未生成音频。
- student 不获得词库权限，但能在在线默写中播放当前复习表 item 对应的 MP3。
- 在线默写播放优先级：服务端 MP3 → 播放失败/缺失 → 浏览器 `speechSynthesis`。
- 不把 TTS 密钥交给 Vue；所有云调用只在 FastAPI 后端执行。
- 不把二进制 MP3 存 SQLite；SQLite 只存音频元数据。

## 采用方案

采用 **方案 B：双读取入口 + 单一生成入口 + 文件落盘 + DB 元数据 + 前端分批循环生成**。

- 管理侧（词库）：`/api/v1/words/{word_id}/audio` 读取/生成，`/api/v1/words/audio/generate-missing` 批量生成。
- 复习侧（student 可用）：`/api/v1/practice-sessions/{session_id}/items/{item_id}/audio` 只允许读取当前复习表 item 的音频，scope 为 `practice:read`。

不采用只用 `/words/{id}/audio` 的方案，因为 student 没有 `words:read`，给 student 开 `words:read` 会破坏「学生只能在线复习」边界。不采用 session-item 级音频绑定，因为会重复存储同一单词音频。

## 数据模型与存储

`Word` 新增音频元数据字段：

- `audio_path: str | null`：音频文件名或相对路径。不得存绝对路径。
- `audio_format: str | null`：Phase 2 固定 `mp3`。
- `audio_voice: str | null`：默认 `Chloe`。
- `audio_generated_at: str | null`：UTC ISO 字符串。
- `audio_bytes: int | null`：文件字节数。

新增迁移 `0004_word_audio.py`，`down_revision="0003"`，使用幂等 guards（若列不存在才 `add_column`）。更新 `/healthz/ready` 期望 revision 到 `0004`，同步 `docker-entrypoint.sh` 注释。

音频文件落盘：

- 默认目录：从 SQLite DB 所在目录推导 `audio/`，生产为 `/app/data/audio/`。也支持 `TTS_AUDIO_DIR` 覆盖。
- 文件名：`word-{id}-{sha12}.mp3`，`sha12 = sha256(en_word + voice + model)[:12]`。
- 生成时写临时文件，flush/fsync 后 `os.replace` 到目标路径，避免半文件。
- 重生成后可以保留旧文件，也可以 best-effort 删除旧文件；删除失败不影响业务，但不应泄露异常给用户。

现有 SQLite 备份不包含 `data/audio/`，文档需明确：Phase 2 音频可再生成，初版不纳入 DB 备份；后续可加 audio zip 备份。

## 配置

在 `Settings` 中新增，沿用 file-wins 风格：

- `TTS_BASE_URL`：默认 `https://api.xiaomimimo.com/v1`
- `TTS_API_KEY_FILE` / `TTS_API_KEY`：文件优先，文件非空校验。
- `TTS_MODEL`：默认 `mimo-v2.5-tts`
- `TTS_VOICE`：默认 `Chloe`
- `TTS_AUDIO_DIR`：可选；缺省由 DB 路径推导。
- `TTS_TIMEOUT_SECONDS`：默认 60。

新增 `settings.tts_enabled`：`tts_base_url` 和 `tts_api_key` 均存在时为 true。

密钥只能通过环境变量或 `_FILE` 提供；不得写入代码、测试、文档示例值、日志或提交历史。

## 后端服务层

新增 `backend/app/services/tts.py`：

- `synthesize_word_mp3(text: str, *, settings: Settings | None = None) -> bytes`
  - 若未配置，抛业务错误 `TTS_NOT_CONFIGURED`。
  - 调用 mimo chat-completions：
    ```json
    {
      "model": "mimo-v2.5-tts",
      "modalities": ["text", "audio"],
      "audio": {"voice": "Chloe", "format": "mp3"},
      "messages": [
        {"role": "user", "content": "Pronounce this English word clearly and naturally for vocabulary dictation."},
        {"role": "assistant", "content": "camera"}
      ]
    }
    ```
  - 解码 `choices[0].message.audio.data`。
  - 上游 HTTP/解析/超时失败统一映射为 `502 TTS_PROVIDER_ERROR`，不打印密钥。

在 `backend/app/services/words.py` 增加：

- `generate_word_audio(db, word_id, *, force=False) -> Word`
  - 查词；已删除或不存在走现有 `not_found`。
  - 已有音频且 `force=false`，直接返回当前 word，不重复调用 TTS。
  - 调 `tts.synthesize_word_mp3`，写 MP3 文件，更新 `audio_*`、`updated_at`、`version += 1`。
- `word_audio_file(word) -> Path | None`
  - 验证 `audio_path` 存在且解析后仍在 audio dir 内；否则返回 None。
- `generate_missing_word_audio(db, limit) -> summary`
  - 按 `id ASC` 找未删除且无音频的词，最多 `limit` 个。
  - 单词失败不中断整批，记录 `failures`。
  - 成功词正常更新 DB；失败词不更新。
  - 返回 `requested/generated/skipped/failed/failures/has_more`。

## 后端 API

### 管理侧（词库）

1. `GET /api/v1/words/{word_id}/audio`
   - scope：`words:read`
   - 返回 `FileResponse(..., media_type="audio/mpeg")`
   - headers：`Content-Disposition: inline`，全局 `nosniff` 已存在。
   - 无文件或无元数据：`404 AUDIO_NOT_FOUND`。

2. `POST /api/v1/words/{word_id}/audio`
   - scope：`words:write`
   - body：`{ "force": false }`
   - 需要 `Idempotency-Key`。
   - 返回更新后的 `word_data`。
   - audit：`word.audio.generate`，target 为 word。

3. `POST /api/v1/words/audio/generate-missing`
   - scope：`words:write`
   - body：`{ "limit": 50 }`，限制 1–100。
   - 需要 `Idempotency-Key`。
   - 同步生成一批，前端循环调用直到 `has_more=false` 或用户取消。
   - 返回：
     ```json
     {
       "requested": 50,
       "generated": 47,
       "skipped": 0,
       "failed": 3,
       "failures": [{"word_id": 12, "en_word": "x", "message": "..."}],
       "has_more": true
     }
     ```

### 复习侧（student 可用）

4. `GET /api/v1/practice-sessions/{session_id}/items/{item_id}/audio`
   - scope：`practice:read`
   - 校验 item 属于 session。
   - 用 item 的 `word_id` 找音频文件。
   - 成功返回 `audio/mpeg`。
   - 无音频：`404 AUDIO_NOT_FOUND`。前端回退浏览器朗读。

更新 `REQUIRED_SCOPES` 并重生成 `backend/contracts/openapi.yaml`。

## Schema 与序列化

`schemas/contracts.py` 新增：

- `WordAudioGenerateRequest(force: bool = False)`
- `WordAudioBatchGenerateRequest(limit: int = 50)`，范围 1–100。

`services/serializers.py::word_data` 增加音频字段：

- `audio_path`
- `audio_format`
- `audio_voice`
- `audio_generated_at`
- `audio_bytes`

前端 `Word` 类型同步字段。

## 前端 API

`frontend/src/api/words.ts` 新增：

- `wordAudioUrl(wordId: number): string`
- `generateWordAudio(wordId: number, force = false): Promise<Word>`
- `generateMissingWordAudio(limit = 50): Promise<WordAudioBatchResult>`

`frontend/src/api/practiceSessions.ts` 新增：

- `sessionItemAudioUrl(sessionId: number, itemId: number): string`

音频播放直接用 URL + `new Audio(url)`；不通过 axios 拉 blob。

## 词库 UI

在 `ResponsiveWordList.vue` 和 `WordCard.vue` 增加动作：

- 有音频：`播放音频` + `重生成`
- 无音频：`生成音频`，播放按钮禁用或隐藏

事件：

- `play-audio(word)`
- `generate-audio(word)`

在 `WordsView.vue`：

- 顶部按钮区新增 `一键生成音频`。
- 单词行点击生成：调用 `generateWordAudio(word.id, Boolean(word.audio_path))`，成功后刷新列表并提示。
- 播放：复用一个页面级 `Audio` 对象；每次播放前先 pause/清旧 src，再播放新 URL；捕获 `play()` reject 并提示。
- 一键生成：循环调用 `generateMissingWordAudio(50)`；显示进度（已生成、失败、批次）；用户可取消（停止下一批，当前请求等待返回）；失败汇总展示，不阻断后续批次。

## 在线默写播放优先级

扩展 `useDictationPlayer`，保持 `dictationEngine` 的 `DictationPlayFn` 合约不变。

- `OnlineDictation.vue` 向 player 提供：`sessionId`、当前 `items`、`sessionItemAudioUrl(sessionId,itemId)`。
- `makePlay` 改为：
  1. 如果当前 index 有 itemId，则先 `new Audio(url)`。
  2. `audio.play()` 成功后等待 `ended` → `hooks.onEnd`。
  3. `audio.error` 或 `play()` reject → 调用原 `speechSynthesis` fallback。
  4. cancel fn 同时能取消当前 audio 或当前 utterance。
- GET 404/403/网络失败都走 fallback，不中断听写。
- `visibilitychange`/`blur`/切表/卸载沿用 engine 的 cancel 链，必须暂停并清空 audio src，旧 `ended` 不能误推进（epoch guard 已覆盖）。

第一版不做 aggressive prefetch；MP3 很小，播放时拉取即可。后续可在 index 变化时预加载下一词。

## 权限

- 生成/重生成：`words:write`。
- 词库播放：`words:read`。
- 默写播放：`practice:read`。
- 不新增 scope，不改变 `ROLE_SCOPES`；student 仍只有在线复习相关权限。

## 错误处理

- `409 TTS_NOT_CONFIGURED`：未配置 TTS。
- `502 TTS_PROVIDER_ERROR`：供应商 HTTP/超时/响应格式失败。
- `404 AUDIO_NOT_FOUND`：没有音频或文件丢失。
- `503 AUDIO_STORAGE_ERROR`：写文件失败。
- 批量生成中单词级失败记录到 `failures`，整批仍返回 200；只有配置缺失这类全局错误才直接失败。

## 测试

### 后端

新增 `backend/tests/test_word_audio.py`：

- 未配置 TTS → `POST /words/{id}/audio` 返回 409。
- mock TTS 返回 MP3 bytes → 生成后 word 有 `audio_*`，文件存在，GET 返回 `audio/mpeg`。
- 已有音频 + `force=false` 不再次调用 TTS。
- `force=true` 重生成并 version+1。
- batch 按 `id ASC`、limit 生效、失败不中断、`has_more` 正确。
- student 无权访问 `/words/{id}/audio` GET/POST。
- student 可访问 `/practice-sessions/{sid}/items/{item_id}/audio`（该 item 有音频时）。

现有后端全套、ruff、OpenAPI drift 需通过。

### 前端

- `useDictationPlayer` 或拆出的 audio play helper 单测：
  - 云音频 play/ended 成功 → 不调用 speechSynthesis。
  - audio error / play reject → fallback speechSynthesis。
  - cancel 时 audio pause/load，旧 ended 不误推进。
- `WordCard`/`ResponsiveWordList` 轻量测试：音频按钮显示与 emit。
- `WordsView` 可测一键生成循环（has_more true→false）。

现有 `npm run typecheck && npm test && npm run build` 需通过。

## 文档与部署

更新：

- `CLAUDE.md`：TTS 配置、音频存储、备份注意、路由权限。
- `deploy/README.md`：NAS 配置 `TTS_API_KEY_FILE`/`TTS_API_KEY`，推荐 `_FILE`；说明 DB 备份不含 `data/audio/`。

部署：

1. 配置 TTS key（推荐 `_FILE`）。
2. Pull/Recreate 后迁移到 `0004`。
3. 词库页点「一键生成音频」逐批生成。
4. `/review` 在线默写优先播放 MP3，无音频时自动回退浏览器。
