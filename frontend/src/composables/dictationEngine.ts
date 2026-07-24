/**
 * dictationEngine — 纯调度状态机（无 Vue、无 DOM）。
 *
 * 职责：按顺序「念」一堆文本，严格遵循在线默写的时序约定——
 *  - 自动模式：间隔从「最后一次播放的 end 事件」起算，而非开始播放时固定计时（长词不会与下一词重叠）。
 *  - 每词可连发 N 次，相邻两次之间留 gap。
 *  - 重播 / 跳过 / 下一个并播放：立即取消当前语音并清掉所有挂起定时器。
 *  - pause()/stop()/dispose()：清定时器、取消当前语音，保留或重置进度。
 *
 * 通过注入 `play`（实际由 useDictationPlayer 用 speechSynthesis 实现，测试用 mock）与
 * `setTimeout`/`clearTimeout`（测试可用 vi.useFakeTimers 接管）来保持可测。
 */
import type { DictationRuntimeSettings, DictationPlayHooks, DictationPlayFn } from './dictationTypes'

export type DictationPhase = 'idle' | 'running' | 'finished'

export interface DictationEngineState {
  phase: DictationPhase
  index: number
  total: number
  isSpeaking: boolean
  counts: { played: number; skipped: number }
}

export interface DictationEngineOptions {
  /** 要默写的文本（按顺序），通常来自 session.items 的 en_word。 */
  texts: () => string[]
  /** 运行期设置（每次调度决策时读取，故中途改动也能生效）。 */
  settings: () => DictationRuntimeSettings
  /** 念一次文本；结束时调 hooks.onEnd/onError；返回一个「取消本次播放」的函数。 */
  play: DictationPlayFn
  /** 每词 N 次连发之间的间隙，默认 500ms。 */
  gapMs?: number
  /** 单次播放若一直不 end/error 的兜底超时，默认 8000ms（防个别浏览器卡死）。 */
  fallbackMs?: number
  /** 状态变化回调（供 composable 同步到 Vue ref）。 */
  onChange?: (state: DictationEngineState) => void
  /** 全部完成回调。 */
  onFinish?: (counts: { played: number; skipped: number }, total: number) => void
}

export interface DictationEngine {
  start(): void
  replay(): void
  skip(): void
  nextAndPlay(): void
  pause(): void
  stop(): void
  dispose(): void
  getState(): DictationEngineState
}

export { type DictationRuntimeSettings, type DictationPlayHooks, type DictationPlayFn } from './dictationTypes'

export function createDictationEngine(opts: DictationEngineOptions): DictationEngine {
  const gapMs = opts.gapMs ?? 500
  const fallbackMs = opts.fallbackMs ?? 8000
  const timers = new Set<ReturnType<typeof setTimeout>>()

  // epoch：每次「换一代」（取消 / 新一次播放 / 推进词）都自增；任何带旧 epoch 的回调一律忽略。
  // 这样 cancel 触发的 end、迟到的 fallback、被取代的旧定时器都不会误推进状态。
  let epoch = 0
  let phase: DictationPhase = 'idle'
  let index = 0
  let repeatIndex = 0
  let isSpeaking = false
  let counts = { played: 0, skipped: 0 }
  let cancelCurrent: (() => void) | null = null

  const total = () => opts.texts().length
  const tick = () => ++epoch
  const emit = () => opts.onChange?.(getState())
  function getState(): DictationEngineState {
    return { phase, index, total: total(), isSpeaking, counts: { ...counts } }
  }

  function scheduleAfter(ms: number, fn: () => void) {
    const handle = setTimeout(fn, ms)
    timers.add(handle)
  }

  function clearAll() {
    tick()
    for (const handle of timers) clearTimeout(handle)
    timers.clear()
    if (cancelCurrent) {
      const cancel = cancelCurrent
      cancelCurrent = null
      try { cancel() } catch { /* 念到一半被取消，忽略底层抛错 */ }
    }
  }

  function finish() {
    clearAll()
    phase = 'finished'
    isSpeaking = false
    emit()
    opts.onFinish?.({ ...counts }, total())
  }

  /** 一次 utterance 结束（end 或 error 或兜底超时）。e 是该次播放捕获的 epoch。 */
  function onUtteranceDone(e: number) {
    if (e !== epoch) return
    repeatIndex += 1
    const { repeat } = opts.settings()
    if (repeatIndex < repeat) {
      // 还有剩余次数：gap 后再念一次。
      scheduleAfter(gapMs, () => {
        if (e !== epoch) return
        speakOnce()
      })
    } else {
      onWordFinished(e)
    }
  }

  /** 当前词的最后一次播放结束。 */
  function onWordFinished(e: number) {
    if (e !== epoch) return
    isSpeaking = false
    emit()
    const { autoAdvance, intervalSec } = opts.settings()
    if (autoAdvance) {
      // 间隔从 end 事件起算；到点推进并念下一词。
      scheduleAfter(intervalSec * 1000, () => {
        if (e !== epoch) return
        leaveCurrent('played')
      })
    }
    // 手动模式：在此等待用户点「下一个并播放」/「跳过」/「重播」。
  }

  function speakOnce() {
    const e = tick()
    const text = opts.texts()[index] ?? ''
    let settled = false
    let fallback: ReturnType<typeof setTimeout> | null = null
    const settle = () => {
      if (settled) return
      settled = true
      if (fallback !== null) { clearTimeout(fallback); timers.delete(fallback) }
      if (e === epoch) onUtteranceDone(e)
    }
    fallback = setTimeout(settle, fallbackMs)
    timers.add(fallback)
    const stop = opts.play(text, { onEnd: settle, onError: settle })
    cancelCurrent = typeof stop === 'function' ? stop : null
  }

  function speakCurrent() {
    if (index >= total()) { finish(); return }
    isSpeaking = true
    repeatIndex = 0
    emit()
    speakOnce()
  }

  /** 离开当前词，进入下一词。bucket 决定当前词计入 已听 / 跳过。 */
  function leaveCurrent(bucket: 'played' | 'skipped') {
    tick()
    counts = { ...counts, [bucket]: counts[bucket] + 1 }
    index += 1
    if (index >= total()) { finish(); return }
    speakCurrent()
  }

  return {
    start() {
      if (phase === 'running') return
      clearAll()
      phase = 'running'
      index = 0
      repeatIndex = 0
      isSpeaking = false
      counts = { played: 0, skipped: 0 }
      emit()
      speakCurrent()
    },
    replay() {
      if (phase !== 'running') return
      clearAll()
      speakCurrent()
    },
    skip() {
      if (phase !== 'running') return
      clearAll()
      leaveCurrent('skipped')
    },
    nextAndPlay() {
      if (phase !== 'running') return
      clearAll()
      leaveCurrent('played')
    },
    /** 暂停：停播放+清定时器，保留进度，不自动续（用于标签页进后台 / 失焦）。 */
    pause() {
      clearAll()
      isSpeaking = false
      emit()
    },
    stop() {
      clearAll()
      phase = 'idle'
      isSpeaking = false
      emit()
    },
    dispose() { clearAll() },
    getState,
  }
}
