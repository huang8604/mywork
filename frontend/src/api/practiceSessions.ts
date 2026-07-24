import { apiClient, newEventId, unwrap } from './client'
import type { ApiEnvelope, BatchRoundResponse, BatchRoundResult, PracticeRound, PracticeSession, ReviewLog, ReviewStatus, StrategyRequest } from '@/types/domain'

export function practiceItemAudioUrl(sessionId: number, itemId: number) { return `/api/v1/practice-sessions/${sessionId}/items/${itemId}/audio` }

export async function generateSession(payload: StrategyRequest, signal?: AbortSignal, idempotencyKey = newEventId()) { return unwrap((await apiClient.post<ApiEnvelope<PracticeSession>>('/daily-table/generate', payload, { signal, headers: { 'Idempotency-Key': idempotencyKey } })).data) }
export async function listSessions(page = 1, size = 20, signal?: AbortSignal, status?: 'active' | 'archived') {
  const response = await apiClient.get<ApiEnvelope<PracticeSession[]>>('/practice-sessions', { params: { page, size, status }, signal })
  return { data: response.data.data, meta: response.data.meta }
}
export async function getSession(id: number, signal?: AbortSignal) { return unwrap((await apiClient.get<ApiEnvelope<PracticeSession>>(`/practice-sessions/${id}`, { signal })).data) }
export async function updateSession(id: number, payload: { title: string | null; note: string | null; expected_version: number }) { return unwrap((await apiClient.patch<ApiEnvelope<PracticeSession>>(`/practice-sessions/${id}`, payload)).data) }
export async function deleteSession(id: number, expectedVersion: number) { await apiClient.delete(`/practice-sessions/${id}`, { params: { expected_version: expectedVersion } }) }
export async function markSessionPrinted(sessionId: number, idempotencyKey = newEventId()) { return unwrap((await apiClient.post<ApiEnvelope<PracticeSession>>(`/practice-sessions/${sessionId}/printed`, undefined, { headers: { 'Idempotency-Key': idempotencyKey } })).data) }
export async function createRound(sessionId: number, mode: 'offline' | 'online', idempotencyKey = newEventId()) { return unwrap((await apiClient.post<ApiEnvelope<PracticeRound>>(`/practice-sessions/${sessionId}/review-rounds`, { mode }, { headers: { 'Idempotency-Key': idempotencyKey } })).data) }
export async function putRoundResult(roundId: number, itemId: number, status: ReviewStatus, eventId: string, expectedVersion?: number) {
  return unwrap((await apiClient.put<ApiEnvelope<ReviewLog>>(`/practice-review-rounds/${roundId}/items/${itemId}/result`, {
    status, client_event_id: eventId, ...(expectedVersion !== undefined ? { expected_version: expectedVersion } : {}),
  })).data)
}
export async function putBatchRoundResults(roundId: number, items: BatchRoundResult[], idempotencyKey: string) {
  return unwrap((await apiClient.put<ApiEnvelope<BatchRoundResponse>>(`/practice-review-rounds/${roundId}/results`, { items }, { headers: { 'Idempotency-Key': idempotencyKey } })).data)
}
export async function downloadRecitation(sessionId: number, format: 'pdf' | 'md') {
  const response = await apiClient.get<Blob>(`/practice-sessions/${sessionId}/recitation`, { params: { format }, responseType: 'blob', timeout: 60_000 })
  const url = URL.createObjectURL(response.data); const link = document.createElement('a')
  link.href = url; link.download = `recitation.${format}`; document.body.appendChild(link); link.click(); link.remove(); URL.revokeObjectURL(url)
}
