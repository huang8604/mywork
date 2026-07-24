/**
 * useDictationPlayer — 把 dictationEngine 接到浏览器 speechSynthesis 与 Vue 生命周期上。
 *
 * - 引擎负责时序（见 dictationEngine.ts）；本 composable 负责「念」的实际实现、音色选择、
 *   生命周期清理（标签页进后台 / 失焦 / 组件卸载 → 暂停或停止）。
 * - Phase 2 接云音频时，只需替换 makePlay：按 wordId 取音频 URL，有则 <audio> 播放，无则回退到此处。
 */
import { onScopeDispose, ref, type Ref } from 'vue'
import { createDictationEngine, type DictationEngineState, type DictationPhase } from './dictationEngine'
import type { DictationPlayFn } from './dictationTypes'
import type { DictationAccent, DictationSettings } from '@/types/domain'

const REPEAT_GAP_MS = 500
const FALLBACK_MS = 8000

export interface DictationPlayer {
  phase: Ref<DictationPhase>
  index: Ref<number>
  total: Ref<number>
  isSpeaking: Ref<boolean>
  counts: Ref<{ played: number; skipped: number }>
  voiceWarning: Ref<string | null>
  supported: boolean
  start(settings: DictationSettings): void
  replay(): void
  skip(): void
  nextAndPlay(): void
  stop(): void
}

function speechSupported(): boolean {
  return typeof window !== 'undefined'
    && 'speechSynthesis' in window
    && typeof window.SpeechSynthesisUtterance !== 'undefined'
}

/** 按口音挑音色；返回 [voice, exact]。exact=false 表示没找到目标口音、用了兜底。 */
function pickVoice(voices: SpeechSynthesisVoice[], accent: DictationAccent): [SpeechSynthesisVoice | null, boolean] {
  if (!voices.length) return [null, false]
  if (accent === 'system') {
    const en = voices.find(v => /^en/i.test(v.lang)) ?? voices[0] ?? null
    return [en, true]
  }
  const want = accent === 'uk' ? 'en-GB' : 'en-US'
  const exact = voices.find(v => v.lang === want)
  if (exact) return [exact, true]
  const samePrefix = voices.find(v => v.lang?.toLowerCase().startsWith(want.toLowerCase().slice(0, 2)))
  const anyEn = voices.find(v => /^en/i.test(v.lang))
  return [samePrefix ?? anyEn ?? voices[0] ?? null, false]
}

export function useDictationPlayer(opts: { texts: () => string[] }): DictationPlayer {
  const supported = speechSupported()
  const phase = ref<DictationPhase>('idle')
  const index = ref(0)
  const total = ref(0)
  const isSpeaking = ref(false)
  const counts = ref({ played: 0, skipped: 0 })
  const voiceWarning = ref<string | null>(null)

  const current = ref<DictationSettings | null>(null)
  const voices = ref<SpeechSynthesisVoice[]>([])

  function loadVoices() {
    if (!supported) return
    const list = window.speechSynthesis.getVoices()
    if (list.length) voices.value = list
  }

  if (supported) {
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

  function makePlay(): DictationPlayFn {
    return (text, hooks) => {
      const synth = window.speechSynthesis
      const settings = current.value
      const accent: DictationAccent = settings?.accent ?? 'us'
      const [voice, exact] = pickVoice(voices.value, accent)
      voiceWarning.value = (!exact && voices.value.length)
        ? `未找到${accent === 'uk' ? '英音' : '美音'}音色，已使用系统默认`
        : null
      const u = new window.SpeechSynthesisUtterance(text)
      if (voice) { u.voice = voice; u.lang = voice.lang }
      else { u.lang = accent === 'uk' ? 'en-GB' : 'en-US' }
      u.rate = settings?.rate ?? 1
      u.pitch = 1
      u.volume = 1
      u.onend = hooks.onEnd
      u.onerror = hooks.onError
      synth.speak(u)
      return () => { try { synth.cancel() } catch { /* 忽略 */ } }
    }
  }

  const engine = createDictationEngine({
    texts: opts.texts,
    settings: () => ({
      autoAdvance: current.value?.autoAdvance ?? true,
      intervalSec: current.value?.intervalSec ?? 5,
      repeat: current.value?.repeat ?? 1,
    }),
    play: makePlay(),
    gapMs: REPEAT_GAP_MS,
    fallbackMs: FALLBACK_MS,
    onChange: sync,
  })

  function start(settings: DictationSettings) {
    if (!supported) return
    current.value = { ...settings }
    voiceWarning.value = null
    // 若音色尚未异步加载完成，这里 voices 为空 → pickVoice 返回 null → 用 lang 兜底，不阻塞。
    const [, exact] = pickVoice(voices.value, settings.accent)
    voiceWarning.value = (!exact && voices.value.length && settings.accent !== 'system')
      ? `未找到${settings.accent === 'uk' ? '英音' : '美音'}音色，已使用系统默认`
      : null
    engine.start()
  }

  // 标签页进后台 / 窗口失焦：立即停播放 + 清定时器（保留进度，回前台不自动续）。
  function onVisibility() {
    if (document.visibilityState === 'hidden') engine.pause()
  }
  function onBlur() { engine.pause() }

  if (typeof document !== 'undefined') {
    document.addEventListener('visibilitychange', onVisibility)
    onScopeDispose(() => document.removeEventListener('visibilitychange', onVisibility))
  }
  if (typeof window !== 'undefined') {
    window.addEventListener('blur', onBlur)
    onScopeDispose(() => window.removeEventListener('blur', onBlur))
  }

  onScopeDispose(() => { try { engine.dispose() } catch { /* 忽略 */ } })

  return {
    phase, index, total, isSpeaking, counts, voiceWarning, supported,
    start,
    replay: () => engine.replay(),
    skip: () => engine.skip(),
    nextAndPlay: () => engine.nextAndPlay(),
    stop: () => engine.stop(),
  }
}
