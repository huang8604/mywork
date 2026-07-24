/** dictationEngine 与 useDictationPlayer 共享的纯类型（无运行时依赖）。 */

/** 引擎运行期需要的设置子集（来自 DictationSettings）。 */
export interface DictationRuntimeSettings {
  autoAdvance: boolean
  intervalSec: number
  repeat: number
}

/** 一次播放的结束回调（end 与 error 都视作「这次念完了」以推进调度）。 */
export interface DictationPlayHooks {
  onEnd: () => void
  onError: () => void
}

/**
 * 念一次文本。
 * 结束时必须调 hooks.onEnd（正常结束）或 hooks.onError（底层失败）之一；
 * 返回一个「取消本次播放」的函数（引擎在重播/跳过/停止时会调用）。
 */
export type DictationPlayFn = (text: string, hooks: DictationPlayHooks, index: number) => () => void
