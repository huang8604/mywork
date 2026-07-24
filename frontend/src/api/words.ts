import type { AxiosRequestConfig } from 'axios'
import { apiClient, newEventId, unwrap } from './client'
import type { ApiEnvelope, AudioProvidersInfo, EnrichedWord, ImportResolved, ImportSummary, Word, WordAudioBatchResult, WordFilters, WordPayload, WordUpdatePayload } from '@/types/domain'

export type { ImportResolved, ImportSummary }
export type ImportResult = ImportSummary
export function wordAudioUrl(id: number) { return `/api/v1/words/${id}/audio` }
export async function generateWordAudio(id: number, force = false, provider?: 'mimo' | 'volc') { return unwrap((await apiClient.post<ApiEnvelope<Word>>(`/words/${id}/audio`, { force, ...(provider ? { provider } : {}) }, { headers: { 'Idempotency-Key': newEventId() } })).data) }
export async function generateMissingWordAudio(limit = 50, provider?: 'mimo' | 'volc') { return unwrap((await apiClient.post<ApiEnvelope<WordAudioBatchResult>>('/words/audio/generate-missing', { limit, ...(provider ? { provider } : {}) }, { headers: { 'Idempotency-Key': newEventId() }, timeout: 120_000 })).data) }
export async function regenerateAllAudio(provider?: 'mimo' | 'volc') { return unwrap((await apiClient.post<ApiEnvelope<{ queued: number; total: number; provider: string | null }>>('/words/audio/regenerate-all', { ...(provider ? { provider } : {}) }, { headers: { 'Idempotency-Key': newEventId() } })).data) }
export async function listAudioProviders() { return unwrap((await apiClient.get<ApiEnvelope<AudioProvidersInfo>>('/words/audio/providers')).data) }

export async function listWords(filters: WordFilters = {}, signal?: AbortSignal) {
  const response = await apiClient.get<ApiEnvelope<Word[]>>('/words', { params: filters, signal, paramsSerializer: { indexes: null } })
  return { data: response.data.data, meta: response.data.meta, requestId: response.data.request_id }
}
export async function getWord(id: number, signal?: AbortSignal) { return unwrap((await apiClient.get<ApiEnvelope<Word>>(`/words/${id}`, { signal })).data) }
export async function enrichWords(words: string[], allowAi = false) { return unwrap((await apiClient.post<ApiEnvelope<EnrichedWord[]>>('/words/enrich', { words, allow_ai: allowAi })).data) }
export async function createWord(payload: WordPayload) { return unwrap((await apiClient.post<ApiEnvelope<Word>>('/words', payload, { headers: { 'Idempotency-Key': newEventId() } })).data) }
export async function updateWord(id: number, payload: WordUpdatePayload) { return unwrap((await apiClient.put<ApiEnvelope<Word>>(`/words/${id}`, payload)).data) }
export async function deleteWord(word: Word) { await apiClient.delete(`/words/${word.id}`, { headers: { 'If-Match': String(word.version) } }) }
export async function restoreWord(word: Word) { return unwrap((await apiClient.post<ApiEnvelope<Word>>(`/words/${word.id}/restore`, { expected_version: word.version })).data) }
export async function resetWordProgress(id: number) { return unwrap((await apiClient.post<ApiEnvelope<Word>>(`/words/${id}/reset-progress`)).data) }
export async function importWords(file: File, conflictPolicy: 'skip' | 'update' | 'reject' = 'update', dryRun = false, unresolvedPolicy: 'skip' | 'reject' | 'ai' = 'ai') {
  const form = new FormData(); form.append('file', file); form.append('conflict_policy', conflictPolicy); form.append('unresolved_policy', unresolvedPolicy); form.append('dry_run', String(dryRun))
  return unwrap((await apiClient.post<ApiEnvelope<ImportSummary>>('/words/import', form, { timeout: 60_000, headers: { 'Idempotency-Key': newEventId() } })).data)
}
export async function exportWords(format: 'csv' | 'json', filters: WordFilters = {}) {
  const config: AxiosRequestConfig = { params: { ...filters, page: undefined, size: undefined, format }, responseType: 'blob', timeout: 60_000, paramsSerializer: { indexes: null } }
  const response = await apiClient.get<Blob>('/words/export', config)
  const url = URL.createObjectURL(response.data); const link = document.createElement('a')
  link.href = url; link.download = `words.${format}`; document.body.appendChild(link); link.click(); link.remove(); URL.revokeObjectURL(url)
}
