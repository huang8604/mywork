import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { createDictationEngine } from '@/composables/dictationEngine'

/** mock play：记录每次念的文本，暴露 fireEnd/fireError 让测试驱动「念完了」事件。
 * cancelFiresEnd=true 时，cancel() 会触发当前 utterance 的 end（模拟真实 speechSynthesis.cancel）。 */
function mockPlay(opts: { cancelFiresEnd?: boolean } = {}) {
  const calls: string[] = []
  const cancelFn = vi.fn(() => { if (opts.cancelFiresEnd) pending?.onEnd() })
  let pending: { onEnd: () => void; onError: () => void } | null = null
  const play = (text: string, hooks: { onEnd: () => void; onError: () => void }) => {
    calls.push(text)
    pending = hooks
    return cancelFn
  }
  return {
    play,
    calls,
    cancelFn,
    fireEnd: () => pending?.onEnd(),
    fireError: () => pending?.onError(),
  }
}

beforeEach(() => vi.useFakeTimers())
afterEach(() => vi.useRealTimers())

describe('dictationEngine — 每词 N 次 + 间隙', () => {
  it('repeat=3 连发 3 次，相邻两次间隔 gap', () => {
    const m = mockPlay()
    const eng = createDictationEngine({
      texts: () => ['a', 'b'],
      settings: () => ({ autoAdvance: false, intervalSec: 5, repeat: 3 }),
      play: m.play, gapMs: 500, fallbackMs: 1e9,
    })
    eng.start()
    expect(m.calls).toEqual(['a'])
    m.fireEnd()                       // 第 1 次结束
    expect(m.calls).toEqual(['a'])
    vi.advanceTimersByTime(1499)      // repeat>1 时 gap = 500+1000 = 1500
    expect(m.calls).toEqual(['a'])
    vi.advanceTimersByTime(1)         // gap 到 → 第 2 次
    expect(m.calls).toEqual(['a', 'a'])
    m.fireEnd()
    vi.advanceTimersByTime(1500)      // 第 3 次
    expect(m.calls).toEqual(['a', 'a', 'a'])
    m.fireEnd()                       // 第 3 次结束 → onWordFinished（手动模式不推进）
    expect(m.calls).toEqual(['a', 'a', 'a'])
    expect(eng.getState().isSpeaking).toBe(false)
  })
})

describe('dictationEngine — 自动模式间隔从最后一次 end 起算', () => {
  it('repeat=3：前两次 end 后推进 intervalSec 不会到下一词；第三次 end 后才计时', () => {
    const m = mockPlay()
    const eng = createDictationEngine({
      texts: () => ['a', 'b'],
      settings: () => ({ autoAdvance: true, intervalSec: 5, repeat: 3 }),
      play: m.play, gapMs: 500, fallbackMs: 1e9,
    })
    eng.start()
    m.fireEnd(); vi.advanceTimersByTime(1500)  // → 第 2 次 (repeat gap 1500)
    m.fireEnd(); vi.advanceTimersByTime(1500)  // → 第 3 次
    expect(m.calls).toEqual(['a', 'a', 'a'])
    // 此时还没触发第 3 次 end：即使等够 intervalSec，也不能播 'b'
    vi.advanceTimersByTime(5000)
    expect(m.calls).toEqual(['a', 'a', 'a'])
    // 第 3 次 end → 才开始计 5s 间隔
    m.fireEnd()
    vi.advanceTimersByTime(4999)
    expect(m.calls).toEqual(['a', 'a', 'a'])
    vi.advanceTimersByTime(1)                  // 5s 到 → 播 'b'
    expect(m.calls).toEqual(['a', 'a', 'a', 'b'])
  })

  it('repeat=1：end 后等 intervalSec 才播下一词', () => {
    const m = mockPlay()
    const eng = createDictationEngine({
      texts: () => ['a', 'b'],
      settings: () => ({ autoAdvance: true, intervalSec: 5, repeat: 1 }),
      play: m.play, gapMs: 500, fallbackMs: 1e9,
    })
    eng.start()
    m.fireEnd()
    vi.advanceTimersByTime(4999)
    expect(m.calls).toEqual(['a'])
    vi.advanceTimersByTime(1)
    expect(m.calls).toEqual(['a', 'b'])
  })
})

describe('dictationEngine — 手动控制立即取消旧语音与定时器', () => {
  it('nextAndPlay：取消当前语音、立即播下一词、计 已听', () => {
    const m = mockPlay()
    const eng = createDictationEngine({
      texts: () => ['a', 'b'],
      settings: () => ({ autoAdvance: false, intervalSec: 5, repeat: 1 }),
      play: m.play, gapMs: 500, fallbackMs: 1e9,
    })
    eng.start()
    expect(m.cancelFn).not.toHaveBeenCalled()
    eng.nextAndPlay()
    expect(m.cancelFn).toHaveBeenCalled()
    expect(m.calls).toEqual(['a', 'b'])
    expect(eng.getState().counts).toEqual({ played: 1, skipped: 0 })
    expect(eng.getState().index).toBe(1)
  })

  it('skip：推进并播放下一词、计 跳过', () => {
    const m = mockPlay()
    const eng = createDictationEngine({
      texts: () => ['a', 'b', 'c'],
      settings: () => ({ autoAdvance: false, intervalSec: 5, repeat: 1 }),
      play: m.play, gapMs: 500, fallbackMs: 1e9,
    })
    eng.start()
    eng.skip()
    expect(m.calls).toEqual(['a', 'b'])
    expect(eng.getState().counts).toEqual({ played: 0, skipped: 1 })
    eng.nextAndPlay()
    expect(m.calls).toEqual(['a', 'b', 'c'])
    expect(eng.getState().counts).toEqual({ played: 1, skipped: 1 })
  })

  it('replay：取消并重播当前词，不计数、不推进', () => {
    const m = mockPlay()
    const eng = createDictationEngine({
      texts: () => ['a', 'b'],
      settings: () => ({ autoAdvance: false, intervalSec: 5, repeat: 1 }),
      play: m.play, gapMs: 500, fallbackMs: 1e9,
    })
    eng.start()
    eng.replay()
    expect(m.cancelFn).toHaveBeenCalled()
    expect(m.calls).toEqual(['a', 'a'])
    expect(eng.getState().index).toBe(0)
    expect(eng.getState().counts).toEqual({ played: 0, skipped: 0 })
  })

  it('nextAndPlay 取消挂起的间隔定时器，不会产生幽灵推进或重复计数', () => {
    const m = mockPlay()
    const eng = createDictationEngine({
      texts: () => ['a', 'b', 'c'],
      settings: () => ({ autoAdvance: true, intervalSec: 5, repeat: 1 }),
      play: m.play, gapMs: 500, fallbackMs: 1e9,
    })
    eng.start()
    m.fireEnd()                // 间隔定时器已挂起
    eng.nextAndPlay()          // 手动推进 → 取消旧定时器，播 'b'
    vi.advanceTimersByTime(100000)  // 旧定时器即使没清也不应再触发
    expect(m.calls).toEqual(['a', 'b'])
    expect(eng.getState().counts).toEqual({ played: 1, skipped: 0 })
    expect(eng.getState().index).toBe(1)
  })

  it('真实 cancel 会触发当前 end：该迟到 end 必须被忽略，不误推进', () => {
    // 真实 speechSynthesis.cancel() 会触发当前 utterance 的 end；
    // 引擎在 clearAll 里先 tick() 再 cancel，故这次 end 的旧 epoch 应被多层守卫丢弃。
    const m = mockPlay({ cancelFiresEnd: true })
    const eng = createDictationEngine({
      texts: () => ['a', 'b', 'c'],
      settings: () => ({ autoAdvance: true, intervalSec: 5, repeat: 1 }),
      play: m.play, gapMs: 500, fallbackMs: 1e9,
    })
    eng.start()          // 'a' 正在念（未手动 fireEnd）
    eng.nextAndPlay()    // clearAll：cancel 触发 'a' 的迟到 end（应被忽略）→ 推进到 'b'
    expect(m.calls).toEqual(['a', 'b'])
    vi.advanceTimersByTime(100000)
    expect(m.calls).toEqual(['a', 'b'])          // 没有幽灵 'c'
    expect(eng.getState().counts).toEqual({ played: 1, skipped: 0 })
    expect(eng.getState().index).toBe(1)
  })
})

describe('dictationEngine — 生命周期', () => {
  it('stop：清掉间隔定时器，之后不再自动推进，phase 回 idle', () => {
    const m = mockPlay()
    const eng = createDictationEngine({
      texts: () => ['a', 'b'],
      settings: () => ({ autoAdvance: true, intervalSec: 5, repeat: 1 }),
      play: m.play, gapMs: 500, fallbackMs: 1e9,
    })
    eng.start()
    m.fireEnd()                // 间隔定时器挂起
    eng.stop()
    vi.advanceTimersByTime(100000)
    expect(m.calls).toEqual(['a'])
    expect(eng.getState().phase).toBe('idle')
  })

  it('pause：清定时器但保留进度与 running 态（用于标签页进后台）', () => {
    const m = mockPlay()
    const eng = createDictationEngine({
      texts: () => ['a', 'b'],
      settings: () => ({ autoAdvance: true, intervalSec: 5, repeat: 1 }),
      play: m.play, gapMs: 500, fallbackMs: 1e9,
    })
    eng.start()
    m.fireEnd()
    eng.pause()
    vi.advanceTimersByTime(100000)
    expect(m.calls).toEqual(['a'])
    expect(eng.getState().phase).toBe('running')
    expect(eng.getState().index).toBe(0)
    expect(eng.getState().isSpeaking).toBe(false)
  })

  it('dispose：清定时器', () => {
    const m = mockPlay()
    const eng = createDictationEngine({
      texts: () => ['a', 'b'],
      settings: () => ({ autoAdvance: true, intervalSec: 5, repeat: 1 }),
      play: m.play, gapMs: 500, fallbackMs: 1e9,
    })
    eng.start()
    m.fireEnd()
    eng.dispose()
    vi.advanceTimersByTime(100000)
    expect(m.calls).toEqual(['a'])
  })
})

describe('dictationEngine — 完成', () => {
  it('最后一个词播完并推进 → finished，onFinish 带上计数', () => {
    const m = mockPlay()
    const onFinish = vi.fn()
    const eng = createDictationEngine({
      texts: () => ['a'],
      settings: () => ({ autoAdvance: true, intervalSec: 5, repeat: 1 }),
      play: m.play, gapMs: 500, fallbackMs: 1e9, onFinish,
    })
    eng.start()
    m.fireEnd()
    vi.advanceTimersByTime(5000)   // 推进 → 越界 → finish
    expect(eng.getState().phase).toBe('finished')
    expect(onFinish).toHaveBeenCalledWith({ played: 1, skipped: 0 }, 1)
  })

  it('error 也视作念完并推进（不卡死）', () => {
    const m = mockPlay()
    const eng = createDictationEngine({
      texts: () => ['a', 'b'],
      settings: () => ({ autoAdvance: false, intervalSec: 5, repeat: 1 }),
      play: m.play, gapMs: 500, fallbackMs: 1e9,
    })
    eng.start()
    m.fireError()
    expect(eng.getState().isSpeaking).toBe(false)
    expect(eng.getState().index).toBe(0)  // 手动模式：error 后等用户，不自动推进
  })
})
