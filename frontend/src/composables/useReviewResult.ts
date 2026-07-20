import { computed, ref } from 'vue'
import { normalizeApiError, type ApiError } from '@/api/client'
import type { ReviewStatus } from '@/types/domain'

export type ReviewPhase = 'unseen' | 'revealed' | 'submitting' | 'submitted' | 'editing' | 'resubmitting' | 'conflict' | 'error'
export function useReviewResult() {
  const phase = ref<ReviewPhase>('unseen'); const confirmed = ref<ReviewStatus | null>(null); const error = ref<ApiError | null>(null)
  function reveal() { if (phase.value === 'unseen') phase.value = 'revealed' }
  async function submit(status: ReviewStatus, action: () => Promise<unknown>) {
    const editing = confirmed.value !== null; phase.value = editing ? 'resubmitting' : 'submitting'; error.value = null
    try { await action(); confirmed.value = status; phase.value = 'submitted'; return true }
    catch (reason) { const normalized = normalizeApiError(reason); error.value = normalized; phase.value = normalized.isConflict ? 'conflict' : 'error'; return false }
  }
  function edit() { if (confirmed.value) phase.value = 'editing' }
  function reset() { phase.value = 'unseen'; confirmed.value = null; error.value = null }
  return { phase, confirmed, error, busy: computed(() => ['submitting', 'resubmitting'].includes(phase.value)), reveal, submit, edit, reset }
}
