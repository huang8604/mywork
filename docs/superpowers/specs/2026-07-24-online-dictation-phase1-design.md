# 在线默写模式（Phase 1 · 浏览器 speechSynthesis）

## 背景

`/review` 页面目前只有「在线卡片」一种在线复习：逐词翻卡、三态回录（known/unknown/skipped），结果写 `ReviewLog`。用户要新增第二种在线模式「在线默写」：**听音 → 黔写**，用于练「耳到手到」。本 spec 是 Phase 1：**纯前端、零后端改动、浏览器原生 `speechSynthesis`**。

云 TTS（mimo）生成高质量 MP3、词库播放/生成按钮、服务端存储，是 **Phase 2**，另立 spec。Phase 1 的播放器接口已为 Phase 2 预留：按 `wordId` 取音频 URL，有则 `<audio>` 播放，无则 `speechSynthesis`——Phase 1 URL 恒空，永远走浏览器。

## 已验证的关键事实（TTS 探勘）

- mimo（`https://api.xiaomimimo.com/v1`）可用：chat-completions 形态，文字放 `assistant` 消息 + `audio:{voice,format}`，返回 `message.audio.data`（base64）。MP3 ≈ 6.6KB/词。
- mimo **只有一个可用音色 `Chloe`**，无英音/美音区分，无 voice 列表端点。→ **英音/美音/系统默认 由浏览器 `speechSynthesis` 承担**（本地 OS 音色有明确 en-US/en-GB）。这正是 Phase 1 的工作。
- 结论：Phase 1 用浏览器 speechSynthesis 既零后端，又能完整支持口音切换；Phase 2 的云音频是「质量默认层」，运行时优先播放，无则回退浏览器。

## 范围与非目标

**范围内（Phase 1）**
- `/review` 顶部新增 `在线卡片 | 在线默写` 切换（不新增第六个主导航）。
- 默写完整交互：选复习表 → 设置 → 开始 → 听写运行屏 → 完成屏。
- 浏览器 `speechSynthesis` 播放，支持口音/语速/间隔/每词次数/自动-手动。

**非目标（明确排除）**
- 不写任何后端、不动 DB、不动 openapi/router/auth。
- **不写 `ReviewLog`**：默写不计结果，学生需自行到「在线卡片」或「结果回录」手动回录。
- 不做答案揭示/自动判对错（极简自检，见决策 2）。
- 不做云 TTS、不做词库播放/生成按钮（Phase 2）。

## 关键设计决策

1. **架构：抽离**。`ReviewView.vue` 变「模式切换壳」（顶部 tab + 分支）；默写交给新组件 `OnlineDictation.vue` + 引擎 composable `useDictationPlayer.ts`；卡片复习逻辑不动。理由：调度器（语音队列 + end 事件定时器 + 生命周期清理）需独立单测；UI 是独立一屏；避免 `ReviewView` 膨胀。符合项目「逻辑进 composable、UI 进组件」习惯。
2. **极简自检**：输入框为草稿区，不校验、不提交、切词清空；不揭示正确答案；只有 `重播 / 跳过 / 下一个并播放`；结束给统计屏。（用户选定）
3. **自动模式间隔从语音 `end` 事件起算**，绝不在开始播放时固定计时——长词不会与下一词重叠。
4. **生命周期清理**：切复习表 / 切回卡片 / 点结束 / 组件卸载 / `visibilitychange`(hidden) / `window.blur` → 立即 `speechSynthesis.cancel()` + 清空全部定时器。回前台不自动续播，交用户手动恢复。
5. **`getVoices()` 兼容**：初次返回空数组时挂 `voiceschanged` 重取。
6. **运行时优先级预留**：player 暴露 `audioUrlFor(wordId)`（Phase 1 恒空）→ 有则 `<audio>` 播放并捕获 `play()` reject 退回手动，无则 `speechSynthesis`。

## 已确认的解释点

- **跳过**：推进到下一词**并播放**（auto/manual 两模式都保持流），被离开的词计 `跳过`（而非 `已听`）。`下一个并播放` 同样推进+播放，但计 `已听`。三者区别清晰且不打断自动流。
- **每词 N 次播放间隙** ≈ 500ms（第 k 次 `end` → 500ms → 第 k+1 次）。

## 详细设计

### 类型（`frontend/src/types/domain.ts` 新增）

```ts
export type DictationAccent = 'us' | 'uk' | 'system'
export interface DictationSettings {
  intervalSec: number      // 2..30, default 5
  autoAdvance: boolean     // default true
  accent: DictationAccent  // default 'us'
  rate: number             // 0.7..1.2, step 0.1, default 1.0
  repeat: number           // 1..3, default 1
}
```

### 播放调度器 `useDictationPlayer.ts`（核心，`frontend/src/composables/`）

对外只暴露：
```ts
{
  state: Ref<'idle'|'running'|'finished'>,
  index: Ref<number>, total: Ref<number>,
  isSpeaking: Ref<boolean>,
  counts: Readonly<Ref<{ played: number; skipped: number }>>,
  voiceWarning: Ref<string | null>,   // 未找到目标口色时的提示
  start(): void,          // 从第 0 词开始（由「开始默写」点击调用 → 满足自动播放策略）
  replay(): void,         // 重播当前词 N 次
  skip(): void,           // 推进+播放下一词，当前词计 skipped
  nextAndPlay(): void,    // 推进+播放下一词，当前词计 played
  stop(): void,           // cancel + 清定时器 + 置 idle/finished
}
```

内部机制：
- **音色选择** `pickVoice(accent)`：挂载时取 `speechSynthesis.getVoices()`；空则监听 `voiceschanged` 重取（只挂一次，取到后移除）。`us`→首个 `lang==='en-US'`；`uk`→首个 `lang==='en-GB'`；`system`→不筛（取默认/首个 en）。找不到目标 → 退回任意 en，再退回默认，并设 `voiceWarning`。
- **发 utterance** `speakOnce(text)`：新建 `SpeechSynthesisUtterance(text)`，设 `voice/lang/rate`，`pitch=1 volume=1`；`speechSynthesis.speak(u)`。返回 `u`。
- **连发 N 次** `speakWord(text)`：递归/链式——发第 1 次；其 `end`（或兜底超时）→ 若次数 < N，`setTimeout(500ms)` 发下一次；第 N 次 `end` → `_onWordFinished()`。
- **`_onWordFinished()`**：`isSpeaking=false`；若 `autoAdvance` → `setTimeout(intervalSec*1000)` 推进并在到点 `speakWord(items[++index])`；若 `index` 越界 → `finish()`。手动模式不排程，等用户。
- **`replay()`**：`_cancelAll()` → 从第 1 次重发当前词。
- **`skip()`**：`counts.skipped++` → `_advanceAndPlay()`。
- **`nextAndPlay()`**：`counts.played++` → `_advanceAndPlay()`。
- **`_advanceAndPlay()`**：`_cancelAll()`；`index++`；越界 → `finish()`；否则 `speakWord(items[index])`。
- **定时器收口**：所有 `setTimeout` 句柄存一个模块内 `Set<number>`；`_cancelAll()` = `speechSynthesis.cancel()` + 逐个 `clearTimeout` + `Set.clear()`。
- **兜底超时**：每次 `speakOnce` 记一个 ~8s 兜底定时器；若 utterance 既未 `end` 也未 `error` 而超时 → 视同 `end` 推进（防个别浏览器卡死）。
- **生命周期**：构造时注册 `document.visibilitychange`（`hidden`→`stop` 播放但保留 `index`/`counts`，置 `isSpeaking=false`，不自动续）与 `window.blur`（→ 同 `cancel`+清定时器，不重置进度）；`onScopeDispose`/`stop()` 时 `cancel`+清定时器+移除监听。

> 注：`speechSynthesis.cancel()` 会触发当前 utterance 的 `end`，需用「正在主动取消」标志位避免 cancel 的 end 被当成正常完成而误推进。

### 组件 `OnlineDictation.vue`（`frontend/src/views/review/`）

Props：`session: PracticeSession`。内部 `useDictationPlayer(session)`。
- **设置态**（运行前）：`el-form` 渲染 5 个设置 + `开始默写` 按钮；若 `!('speechSynthesis' in window)` → 显示不支持并禁用按钮。
- **运行态**：题号 `{{ index+1 }} / {{ total }}` + `el-progress`；草稿 `el-input`（`v-model` 本地 `draft`，watch `index` 变化清空）；控制按钮 `重播 / 跳过 / 下一个并播放`（`isSpeaking` 时可禁用「下一个」避免抢拍，可选）；底部设置摘要 + 播放指示 + `voiceWarning`（若有）；`结束` 按钮调 `stop()` 回设置态。
- **完成态**：统计（总词数 / 已听 / 跳过 / 用时 `Date` 差，开始时记起止时间）；按钮 `再来一次`（重置 player + 回运行态第 0 词）、`返回设置`、`返回卡片`(emit)。

### `ReviewView.vue` 改动（最小）

- 顶部加 `el-segmented`（`在线卡片 | 在线默写`，本地 `mode` ref，默认 `cards`）。
- `mode==='dictation'` 且已选 session → `<OnlineDictation :session @back-to-cards="mode='cards'">`；否则原卡片 UI。
- 切换 `mode` 或 `selectedSessionId` 变化时，若默写在跑由组件 `unmount` 自动 `stop`（composable 的 `onScopeDispose` 兜底）。

### 错误与降级

- 无 `speechSynthesis`：设置态禁用开始 + 提示。
- utterance `error` 事件：视同 `end` 推进（不卡死）。
- 兜底超时：见调度器。
- Phase 2 的 `<audio>` `play()` reject（自动播放策略）：Phase 1 不触发，接口预留。

## 测试（`frontend/tests/unit/`）

`dictationPlayer.spec.ts`（jsdom + 手动 mock `window.speechSynthesis`）：
1. 自动模式：间隔定时器**只在第 N 次 `end` 后**启动（前 N-1 次 `end` 不排程）。
2. `replay()` / `nextAndPlay()`：立即触发 `cancel()` 并清掉旧定时器（旧定时器回调不再推进）。
3. N=3：连发 3 次（中间隔由 `end` 链驱动）。
4. `skip()`：`skipped++` 且推进+播放；`nextAndPlay()`：`played++` 且推进+播放。
5. `stop()`：清空全部定时器 + `cancel` + 监听移除。
6. `visibilitychange=hidden`：触发 `cancel` + 清定时器，不自动续。
7. （可选）`pickVoice`：mock voices 列表，`us`/`uk`/`system` 各取对；空数组→等 `voiceschanged`。
8. （可选）cancel-triggered-end 不误推进（标志位）。

e2e 不做（无头环境无语音）。

## 落点文件（Phase 1）

- 新：`frontend/src/composables/useDictationPlayer.ts`、`frontend/src/views/review/OnlineDictation.vue`、`frontend/tests/unit/dictationPlayer.spec.ts`
- 改：`frontend/src/views/ReviewView.vue`、`frontend/src/types/domain.ts`
- 不动：后端、`contracts/openapi.yaml`、router、auth、CI

## Phase 2 预留（非本 spec，仅备忘）

- 后端：`Word` 加 `audio_path`/`audio_*` 字段 + 迁移；`services/tts.py`（mimo chat-completions，base64→MP3 存 `/app/data/audio/`）；`api/practice.py` 或 `api/words.py` 加 `POST /words/{id}/audio`（生成）、`GET /words/{id}/audio`（流式 MP3）、`POST /words/generate-audio-batch`（一键生成未生成的，按序）；config 加 `TTS_BASE_URL/TTS_API_KEY(_FILE)/TTS_VOICE`。
- 前端：词库行加 播放/生成音频 按钮 + 一键生成；`useDictationPlayer` 的 `audioUrlFor(wordId)` 接通 `GET /words/{id}/audio`。
- 运行时优先级：有云音频 → `<audio>` 播放；无 → `speechSynthesis`（Phase 1 现状）。
