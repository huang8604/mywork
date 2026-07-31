/**
 * useDictationPlayer — 把 dictationEngine 接到云音频 / 浏览器 speechSynthesis 与 Vue 生命周期上。
 *
 * - 引擎负责时序（见 dictationEngine.ts）；本 composable 负责「念」的实际实现、音色选择、
 *   生命周期清理（标签页进后台 / 失焦 / 组件卸载 → 暂停或停止）。
 * - Phase 2：优先播放服务端 MP3；404/播放失败时自动降级到浏览器 speechSynthesis。
 */
import { onScopeDispose, ref, type Ref } from 'vue'
import { createDictationEngine, type DictationEngineState, type DictationPhase } from './dictationEngine'
import type { DictationPlayFn, DictationPlayHooks } from './dictationTypes'
import type { DictationLanguage, DictationSettings } from '@/types/domain'

const REPEAT_GAP_MS = 500
const FALLBACK_MS = 8000

export interface DictationPlayer {
  phase: Ref<DictationPhase>
  index: Ref<number>
  total: Ref<number>
  isSpeaking: Ref<boolean>
  paused: Ref<boolean>
  counts: Ref<{ played: number; skipped: number }>
  voiceWarning: Ref<string | null>
  supported: boolean
  start(settings: DictationSettings): void
  replay(): void
  skip(): void
  nextAndPlay(): void
  pause(): void
  resume(): void
  stop(): void
}

function speechSupported(): boolean {
  return typeof window !== 'undefined'
    && 'speechSynthesis' in window
    && typeof window.SpeechSynthesisUtterance !== 'undefined'
}

function audioSupported(): boolean {
  return typeof window !== 'undefined' && typeof Audio !== 'undefined'
}

/** 按默写语言挑音色；英文固定英音，中文固定普通话。 */
function pickVoice(voices: SpeechSynthesisVoice[], language: DictationLanguage): [SpeechSynthesisVoice | null, boolean] {
  if (!voices.length) return [null, false]
  const want = language === 'zh' ? 'zh-CN' : 'en-GB'
  const exact = voices.find(v => v.lang?.toLowerCase() === want.toLowerCase())
  if (exact) return [exact, true]
  const samePrefix = voices.find(v => v.lang?.toLowerCase().startsWith(language))
  return [samePrefix ?? voices[0] ?? null, false]
}

export function useDictationPlayer(opts: { texts: () => string[]; audioUrls?: () => string[]; numberAudioUrl?: (pos: number) => string }): DictationPlayer {
  const hasSpeech = speechSupported()
  const hasAudio = audioSupported()
  const supported = hasSpeech || hasAudio
  const phase = ref<DictationPhase>('idle')
  const index = ref(0)
  const total = ref(0)
  const isSpeaking = ref(false)
  const paused = ref(false)
  const counts = ref({ played: 0, skipped: 0 })
  const voiceWarning = ref<string | null>(null)

  const current = ref<DictationSettings | null>(null)
  const voices = ref<SpeechSynthesisVoice[]>([])

  // 「本词序号是否已播报过」:每词只播一次 "number N"(repeat 重复不重播);replay/start 重置。
  let announcedWordIndex = -1

  // 复用单个 <audio> 元素:首词由「开始默写」点击手势同步解锁(bless),之后自动到下一词经
  // setTimeout 触发的播放复用同一个已解锁元素。若每词 new Audio(),新元素在 iOS Safari /
  // 部分 Android 上会被自动播放策略静默拦截 → 自动到下一词没声音。
  const sharedAudio: HTMLAudioElement | null = hasAudio ? new Audio() : null
  if (sharedAudio) sharedAudio.preload = 'auto'

  function loadVoices() {
    if (!hasSpeech) return
    const list = window.speechSynthesis.getVoices()
    if (list.length) voices.value = list
  }

  if (hasSpeech) {
    loadVoices()
    // getVoices() 首次常返回空数组，需等 voiceschanged。
    const onVoicesChanged = () => loadVoices()
    window.speechSynthesis.addEventListener?.('voiceschanged', onVoicesChanged)
    onScopeDispose(() => window.speechSynthesis.removeEventListener?.('voiceschanged', onVoicesChanged))
  }

  function sync(state: DictationEngineState) {
    phase.value = state.phase
    index.value = state.index
    total.value = state.total
    isSpeaking.value = state.isSpeaking
    counts.value = state.counts
  }

  function makeSpeechPlay(): DictationPlayFn {
    return (text, hooks) => {
      if (!hasSpeech) {
        hooks.onError()
        return () => {}
      }
      const synth = window.speechSynthesis
      const settings = current.value
      const language: DictationLanguage = settings?.language ?? 'en'
      const [voice, exact] = pickVoice(voices.value, language)
      voiceWarning.value = (!exact && voices.value.length)
        ? `未找到${language === 'zh' ? '中文普通话' : '英音'}音色，已使用系统默认`
        : null
      const u = new window.SpeechSynthesisUtterance(text)
      if (voice) { u.voice = voice; u.lang = voice.lang }
      else { u.lang = language === 'zh' ? 'zh-CN' : 'en-GB' }
      u.rate = settings?.rate ?? 1
      u.pitch = 1
      u.volume = 1
      u.onend = hooks.onEnd
      u.onerror = hooks.onError
      // Chrome speechSynthesis 长期 bug:连续 speak()(下一词 / 重复第 2 次)若不在前面
      // cancel() 清队列,会卡住 → 第 2 个起静音或不触发 onend(表现就是「自动到下一词没声音」)。
      // 引擎保证上一次 onend 已处理完才发下一次 speak(永远经 scheduleAfter 定时器,不从 onend
      // 同步重入),所以这里 cancel() 队列为空 = no-op,只起「冲掉卡住状态」的作用。
      try { synth.cancel() } catch { /* 忽略 */ }
      synth.speak(u)
      return () => { try { synth.cancel() } catch { /* 忽略 */ } }
    }
  }

  function makePlay(): DictationPlayFn {
    const speechPlay = makeSpeechPlay()

    // Play the WORD clip on the shared element (cloud preferred, speechSynthesis
    // fallback). Returns a cancel fn. Same logic as before extraction.
    const playWord = (
      text: string,
      hooks: DictationPlayHooks,
      wordIndex: number,
      url: string | undefined,
    ): (() => void) => {
      if (!url || !sharedAudio) return speechPlay(text, hooks, wordIndex)

      const audio = sharedAudio
      let cancelled = false
      let fallbackCancel: (() => void) | null = null
      let usingFallback = false

      // 复用元素:只摘事件 + pause,不 removeAttribute('src')(那会让某些浏览器把元素当新元素、
      // 重新要求手势)。下一次播放会重新赋 src + load。
      const detach = () => {
        audio.onended = null
        audio.onerror = null
      }
      const abandonAudio = () => {
        detach()
        audio.pause()
      }
      const fallback = () => {
        if (cancelled || usingFallback) return
        usingFallback = true
        abandonAudio()
        voiceWarning.value = '云音频不可用，已使用浏览器语音兜底'
        fallbackCancel = speechPlay(text, hooks, wordIndex)
      }

      audio.onended = () => {
        if (cancelled) return
        detach()
        hooks.onEnd()
      }
      audio.onerror = fallback
      audio.playbackRate = current.value?.rate ?? 1
      // 复用已解锁元素:换 src + load + play。新 src 自动让 currentTime 归零。
      try {
        audio.src = url
        audio.load()
      } catch { /* 忽略 */ }
      audio.play().catch((err: unknown) => {
        // 诊断证据:autoplay 拦截(NotAllowedError)/ 网络 / 解码失败在此暴露,方便定位。
        const name = (err as { name?: string } | null)?.name
        const msg = (err as { message?: string } | null)?.message
        if (typeof console !== 'undefined') console.warn('[dictation] audio play failed:', name, msg, 'wordIndex=', wordIndex)
        fallback()
      })

      return () => {
        cancelled = true
        abandonAudio()
        if (fallbackCancel) fallbackCancel()
      }
    }

    return (text, hooks, wordIndex) => {
      const url = opts.audioUrls?.()[wordIndex]
      const pos = wordIndex + 1
      // 每词只播一次序号:repeat 重复(wordIndex === announcedWordIndex)、超出 1..50、
      // 或走 speechSynthesis 兜底(无 sharedAudio)时,直接播正文。
      const shouldAnnounce =
        !!opts.numberAudioUrl
        && !!sharedAudio
        && pos >= 1 && pos <= 50
        && wordIndex !== announcedWordIndex
      if (shouldAnnounce) announcedWordIndex = wordIndex
      const numberUrl = shouldAnnounce ? opts.numberAudioUrl!(pos) : null
      if (!numberUrl) return playWord(text, hooks, wordIndex, url)

      // 先在同一个已解锁的 shared <audio> 上播 "number N",结束/失败后无缝换 src 播单词。
      // 序号缺失/被拦(404、autoplay)→ 静默跳过、直接播单词,不阻断默写。
      const audio = sharedAudio!
      let cancelled = false
      let startedWord = false
      let wordCancel: (() => void) | null = null
      const detachNumber = () => { audio.onended = null; audio.onerror = null }
      const goWord = () => {
        if (cancelled || startedWord) return
        startedWord = true
        detachNumber()
        audio.pause()
        wordCancel = playWord(text, hooks, wordIndex, url)
      }
      audio.onended = goWord
      audio.onerror = goWord
      audio.playbackRate = current.value?.rate ?? 1
      try {
        audio.src = numberUrl
        audio.load()
      } catch { goWord(); return () => {} }
      audio.play().catch(goWord)

      return () => {
        cancelled = true
        detachNumber()
        audio.pause()
        if (wordCancel) wordCancel()
      }
    }
  }

  const engine = createDictationEngine({
    texts: opts.texts,
    settings: () => ({
      autoAdvance: current.value?.autoAdvance ?? true,
      intervalSec: current.value?.intervalSec ?? 6,
      repeat: current.value?.repeat ?? 1,
    }),
    play: makePlay(),
    gapMs: REPEAT_GAP_MS,
    fallbackMs: FALLBACK_MS,
    onChange: sync,
  })

  function start(settings: DictationSettings) {
    if (!supported) return
    announcedWordIndex = -1
    current.value = { ...settings }
    paused.value = false
    voiceWarning.value = null
    // 若音色尚未异步加载完成，这里 voices 为空 → pickVoice 返回 null → 用 lang 兜底，不阻塞。
    const [, exact] = pickVoice(voices.value, settings.language)
    voiceWarning.value = (!exact && voices.value.length)
      ? `未找到${settings.language === 'zh' ? '中文普通话' : '英音'}音色，已使用系统默认`
      : null
    engine.start()
  }

  // 标签页进后台 / 窗口失焦：立即停播放 + 清定时器（保留进度，回前台不自动续）。
  function onVisibility() {
    if (document.visibilityState === 'hidden') { engine.pause(); paused.value = true }
  }
  function onBlur() { engine.pause(); paused.value = true }

  if (typeof document !== 'undefined') {
    document.addEventListener('visibilitychange', onVisibility)
    onScopeDispose(() => document.removeEventListener('visibilitychange', onVisibility))
  }
  if (typeof window !== 'undefined') {
    window.addEventListener('blur', onBlur)
    onScopeDispose(() => window.removeEventListener('blur', onBlur))
  }

  onScopeDispose(() => {
    try { if (sharedAudio) { sharedAudio.pause(); sharedAudio.removeAttribute('src') } } catch { /* 忽略 */ }
    try { engine.dispose() } catch { /* 忽略 */ }
  })

  return {
    phase, index, total, isSpeaking, paused, counts, voiceWarning, supported,
    start,
    replay: () => { paused.value = false; announcedWordIndex = -1; return engine.replay() },
    skip: () => { paused.value = false; return engine.skip() },
    nextAndPlay: () => { paused.value = false; return engine.nextAndPlay() },
    pause: () => { engine.pause(); paused.value = true },
    resume: () => { paused.value = false; announcedWordIndex = -1; engine.replay() },
    stop: () => { paused.value = false; engine.stop() },
  }
}
