import { computed, onBeforeUnmount, ref } from 'vue'
import { ApiError, normalizeApiError } from '@/api/client'
import type { AsyncPhase } from '@/types/domain'

export function useAsyncState<T>(initial?: T) {
  const data = ref<T | undefined>(initial); const phase = ref<AsyncPhase>('idle'); const error = ref<ApiError | null>(null)
  let controller: AbortController | null = null
  async function run(task: (signal: AbortSignal) => Promise<T>) {
    controller?.abort(); controller = new AbortController(); phase.value = 'loading'; error.value = null
    try {
      const result = await task(controller.signal); data.value = result
      phase.value = Array.isArray(result) && result.length === 0 ? 'empty' : 'success'; return result
    } catch (reason) {
      const normalized = normalizeApiError(reason); if (normalized.isCanceled) return undefined
      error.value = normalized; phase.value = 'error'; throw normalized
    }
  }
  function cancel() { controller?.abort() }
  onBeforeUnmount(cancel)
  return { data, phase, error, loading: computed(() => phase.value === 'loading'), run, cancel }
}
