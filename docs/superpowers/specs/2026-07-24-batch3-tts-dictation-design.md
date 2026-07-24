# Batch-3: 双 TTS 模型 + 默认值调整 + 导入后台生成音频 设计

> 日期 2026-07-24。覆盖用户提出的 7 项改动:默写重复间隔/语速/默认英音、复习表默认数量、英音清晰有力提示词、导入后后台生成音频、新增豆包 seed-tts-2.0 第二模型 + 模型选择 + 全部重生成。

## 背景与已确认事实

- mimo TTS(已上线):`POST {TTS_BASE_URL}/chat/completions`,body 含 `modalities:["text","audio"]` + `audio.voice` + assistant 内容为要念的词,响应 `choices[0].message.audio.data` 为 base64 mp3。唯一已验证音色 `Chloe`。
- 豆包 seed-tts-2.0(本次新增,契约已实测):
  - 入口 **agent-plan 专属**:`POST https://openspeech.bytedance.com/api/v3/plan/tts/unidirectional?api_key=<ARK_KEY>`(key 必须走 query `?api_key=`,纯 Bearer 会被打回 "app key not found")。
  - 头:`X-Api-Resource-Id: seed-tts-2.0`、`Content-Type: application/json`。
  - body:`{"req_params":{"text":"<词>","model":"doubao-seed-tts-2.0","voice_type":"<音色>","encoding":"mp3","speed":0.9}}`。
  - 错误响应:`{"reqid","code","message"}`(JSON);成功响应字段待账号开通后确认,适配器用防御式解析(优先二进制,否则 JSON 取 base64)。
  - **账号前置**:火山方舟控制台需「配置模型 + 开启超额后付费」并绑定 seed-tts-2.0;未开通时网关返回 `code:45000010 ... call ark get 401`。`/api/v3/models` 当前不含任何 TTS 模型即此症状。
- 后端无任务队列、单 uvicorn worker、单租户(owner)。导入是同步事务;TTS 生成慢(每词一次远端调用)。

## 关键决策(已与用户确认)

1. **导入后台生成音频**:独立守护线程 worker,每个词各自短命 `SessionLocal`,失败仅告警。进程重启中断可用「一键生成」补齐。默认开,`TTS_AUTO_GENERATE_ON_IMPORT`(默认 true)可关。
2. **模型选择**:全局「本次操作选模型」(词库页下拉,带 `provider` 参数),不持久化、不加列。
3. **全部重新生成**:全部未删除词 `force=True` 入队 worker。
4. **不新增 DB 列**;`audio_voice` 已能区分音色(Chloe / BV…)。
5. **云音频固定英音**;默写页口音开关只影响 `speechSynthesis` 兜底。

## 改动清单

### A. 默写调整(项 1/2/3)— 纯前端
- `frontend/src/views/review/OnlineDictation.vue`:`settings` 默认 `accent:'uk'`、`rate:0.8`。
- `frontend/src/composables/dictationEngine.ts`:`onUtteranceDone` 安排下一次重复时,间隔 = `gapMs + (1000 if repeat>1 else 0)`。词间 `intervalSec` 不变。

### B. 复习表默认数量(项 7)— 纯前端
- `frontend/src/views/DailyGenerateView.vue`:`form` 初值 `{new_words_limit:4,error_words_limit:3,due_words_limit:3,custom_words_limit:0}`(原 10/5/5/5)。预设按钮保留。

### C. TTS 提示词(项 6)— `backend/app/services/tts.py`
- 统一 `PROMPT`:要求英音、清晰、有力,发声前后各留一丝停顿。两 provider 共用。

### D. 第二 TTS 模型(项 5)— config + tts.py
- `Settings` 新增:`volc_base_url`(默认 `https://openspeech.bytedance.com`)、`volc_api_key(_file)`、`volc_model`(默认 `doubao-seed-tts-2.0`)、`volc_resource_id`(默认 `seed-tts-2.0`)、`volc_voice`(默认英音候选,待开通后定,先 `BV700_V2_streaming`)、`volc_timeout_seconds`(默认 60);属性 `volc_enabled`。
- `Settings` 新增 `tts_provider`(默认 `mimo`)、`tts_auto_generate_on_import`(默认 true)。
- `tts.py` 重构:`synthesize_word_mp3(text, *, provider=None, settings=None)` 分派到 `_synthesize_mimo` / `_synthesize_volc`。`provider` 默认 `settings.tts_provider`;若该 provider 未配置则回退到任一已配置者,都未配置则 `409 TTS_NOT_CONFIGURED`。
- `_synthesize_volc`:`urllib.request.Request(volc_base_url+"/api/v3/plan/tts/unidirectional?api_key="+key, method=POST, headers={Content-Type, X-Api-Resource-Id: volc_resource_id})`,body `{"req_params":{text,model,voice_type:volc_voice,encoding:"mp3",speed:0.9}}`。响应防御式解析:二进制(以 `\xff\xf3`/`\xff\xfb`/`ID3` 开头)直接用;否则 JSON 取 `data`/`audio` base64;失败 `502 TTS_PROVIDER_ERROR`。代码注释标注「契约已实测至 acquire 步骤;模型待账号开通后验证音频字段」。
- `generate_word_audio(db, word_id, *, force, provider=None)` 透传 provider;`audio_voice` 记录实际音色。

### E. Provider 元数据 + 生成端点(项 5)— 路由 + scopes
- `GET /api/v1/words/audio/providers`(admin,`words:read`):返回 `{current, default, providers:[{id,label,enabled,voice,model}]}`。`current` = `settings.tts_provider`(若未配置则首个 enabled);mimo enabled = `tts_enabled`,volc enabled = `volc_enabled`。
- `POST /api/v1/words/{word_id}/audio`:body 增可选 `provider`。
- `POST /api/v1/words/audio/generate-missing`:body 增可选 `provider`。
- 新 `POST /api/v1/words/audio/regenerate-all`(admin,必带 `Idempotency-Key`,body 可选 `provider`):选全部未删除词 id,`force=True` 入队 worker,返回 `{queued:N}`。
- `REQUIRED_SCOPES` 加这几条(均 admin/`words:*`)。

### F. 导入后台生成音频(项 4)— 新 `app/services/audio_worker.py` + import 路由
- `audio_worker.py`:模块级 `queue.Queue` + `set` 去重 + 单守护线程(lazy 启动)。`enqueue(word_ids, *, force=False, provider=None)`;循环里每个词开 `SessionLocal`→`generate_word_audio(force=force, provider=provider)`→commit→close;`AppError`/其它异常 `logger.warning` 并继续。
- `app/api/words.py::import_words`:提交后,若 `(settings.tts_enabled or settings.volc_enabled) and settings.tts_auto_generate_on_import`,把本次 `created` 的 word_id 入队(`force=False`,`provider=None` 由 worker 按默认 provider 生成);响应 `data` 增 `audio_generation:{queued:N}`。单词 `POST /words` 不触发。

### G. 前端(项 4/5)
- `frontend/src/api/words.ts`:`generateWordAudio(id, force, provider?)`、`generateMissingWordAudio(limit, provider?)`、`regenerateAllAudio(provider?)`、`listAudioProviders()`。
- `frontend/src/types/domain.ts`:`AudioProvider`、`AudioProvidersInfo`、`WordAudioBatchResult` 复用。
- `WordsView.vue`:顶部 provider 下拉(拉 `/providers`,只列 enabled,默认 `current`)+「全部重新生成」按钮;三个生成动作带所选 provider;导入后若 `audio_generation.queued` toast「音频后台生成中(共 N 个)」。
- 导入并生成(`DailyGenerateView`)走 import,自动享受后台生成,无需改。

### H. 测试
- `tests/test_word_audio.py` 扩展:mock `_synthesize_mimo`/`_synthesize_volc`,断言 provider 分派;`regenerate-all` 入队全量 force;`/providers` 返回结构;worker 处理函数(直接调,断言逐词生成 + 失败不中断);import 后 `audio_generation.queued`。conftest 保持 TTS 默认关。

### I. 文档/部署/契约
- `CLAUDE.md`、`deploy/README.md`、`deploy/portainer-stack.template.yml` 补 Volcengine env + 「需在火山方舟控制台配置模型 + 开启超额后付费」+ agent-plan URL 说明;`export_openapi.py` 重生成。

## 验证
- 后端:`pytest -q` 全绿(含 provider/worker/regenerate-all);`ruff check`;`git diff --exit-code -- contracts/openapi.yaml`。
- 前端:`npm run typecheck && npm test && npm run build`。
- Volcengine 真实音频:账号开通后部署时验证;若响应字段与推断不符,仅调 `_synthesize_volc`。
