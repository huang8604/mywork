import type { AxiosRequestConfig } from 'axios'
import { apiClient, newEventId, unwrap } from './client'
import type { ApiEnvelope, EnrichedWord, ImportSummary, Word, WordFilters, WordPayload, WordUpdatePayload } from '@/types/domain'

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
export async function importWords(file: File, conflictPolicy: 'skip' | 'update' | 'reject', dryRun = false, unresolvedPolicy: 'skip' | 'reject' | 'ai' = 'reject') {
  const form = new FormData(); form.append('file', file); form.append('conflict_policy', conflictPolicy); form.append('unresolved_policy', unresolvedPolicy); form.append('dry_run', String(dryRun))
  return unwrap((await apiClient.post<ApiEnvelope<ImportSummary>>('/words/import', form, { timeout: 60_000, headers: { 'Idempotency-Key': newEventId() } })).data)
}
export async function exportWords(format: 'csv' | 'json', filters: WordFilters = {}) {
  const config: AxiosRequestConfig = { params: { ...filters, page: undefined, size: undefined, format }, responseType: 'blob', timeout: 60_000, paramsSerializer: { indexes: null } }
  const response = await apiClient.get<Blob>('/words/export', config)
  const url = URL.createObjectURL(response.data); const link = document.createElement('a')
  link.href = url; link.download = `words.${format}`; document.body.appendChild(link); link.click(); link.remove(); URL.revokeObjectURL(url)
}
