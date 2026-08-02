import type { AxiosRequestConfig } from 'axios'
import { apiClient, newEventId, unwrap } from './client'
import type { ApiEnvelope, AudioBatchResult, AudioProgress, AudioProvidersInfo, AudioProvider, BatchDeleteResult, BatchItem, BatchResetResult, BatchTagsResult, EnrichedWord, ImportProgress, ImportResolved, ImportSummary, Word, WordFilters, WordPayload, WordUpdatePayload } from '@/types/domain'

export type { ImportResolved, ImportSummary, ImportProgress }
export type ImportResult = ImportSummary
export function wordAudioUrl(id: number, language: 'en' | 'zh' = 'en') { return `/api/v1/words/${id}/audio?language=${language}` }
export async function generateWordAudio(id: number, force = false, provider?: 'mimo' | 'volc') { return unwrap((await apiClient.post<ApiEnvelope<Word>>(`/words/${id}/audio`, { force, ...(provider ? { provider } : {}) }, { headers: { 'Idempotency-Key': newEventId() } })).data) }
export async function generateMissingWordAudio(limit = 50, provider?: 'mimo' | 'volc') { return unwrap((await apiClient.post<ApiEnvelope<AudioBatchResult>>('/words/audio/generate-missing', { limit, ...(provider ? { provider } : {}) }, { headers: { 'Idempotency-Key': newEventId() } })).data) }
export async function regenerateAllAudio(provider?: 'mimo' | 'volc') { return unwrap((await apiClient.post<ApiEnvelope<AudioBatchResult>>('/words/audio/regenerate-all', { ...(provider ? { provider } : {}) }, { headers: { 'Idempotency-Key': newEventId() } })).data) }
export async function generateNumberAudio(provider?: 'mimo' | 'volc', force = false) { return unwrap((await apiClient.post<ApiEnvelope<AudioBatchResult>>('/words/audio/generate-numbers', { ...(provider ? { provider } : {}), force }, { headers: { 'Idempotency-Key': newEventId() } })).data) }
export async function listAudioProgress() { return unwrap((await apiClient.get<ApiEnvelope<AudioProgress>>('/words/audio/progress')).data) }
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
export async function startImport(file: File, opts: { conflictPolicy: 'skip' | 'update' | 'reject'; unresolvedPolicy: 'skip' | 'reject' | 'ai'; dryRun: boolean; tags: string[] }) {
  const form = new FormData()
  form.append('file', file)
  form.append('conflict_policy', opts.conflictPolicy)
  form.append('unresolved_policy', opts.unresolvedPolicy)
  form.append('dry_run', String(opts.dryRun))
  if (opts.tags.length) form.append('tags', opts.tags.join(','))
  // dry_run returns an ImportSummary preview synchronously; a real import returns
  // an ImportProgress snapshot immediately (the job runs in the background).
  return unwrap((await apiClient.post<ApiEnvelope<ImportSummary | ImportProgress>>('/words/import', form, { headers: { 'Idempotency-Key': newEventId() } })).data)
}
export async function listImportProgress() { return unwrap((await apiClient.get<ApiEnvelope<ImportProgress>>('/words/import/progress')).data) }
export async function awaitImportDone(timeoutMs = 120_000, pollMs = 500): Promise<ImportProgress> {
  // Poll until the background import finishes; used by flows that need the
  // final resolved[] (e.g. import-then-generate-worksheet).
  const deadline = Date.now() + timeoutMs
  while (Date.now() < deadline) {
    const p = await listImportProgress()
    if (p.finished) return p
    await new Promise(resolve => setTimeout(resolve, pollMs))
  }
  return listImportProgress()
}
export async function batchDeleteWords(items: BatchItem[]) { return unwrap((await apiClient.post<ApiEnvelope<BatchDeleteResult>>('/words/batch/delete', { items }, { headers: { 'Idempotency-Key': newEventId() } })).data) }
export async function batchSetTags(items: BatchItem[], tags: string[]) { return unwrap((await apiClient.post<ApiEnvelope<BatchTagsResult>>('/words/batch/tags', { items, tags }, { headers: { 'Idempotency-Key': newEventId() } })).data) }
export async function batchGenerateAudio(wordIds: number[], provider?: AudioProvider) { return unwrap((await apiClient.post<ApiEnvelope<AudioBatchResult>>('/words/batch/audio', { word_ids: wordIds, ...(provider ? { provider } : {}) }, { headers: { 'Idempotency-Key': newEventId() } })).data) }
export async function batchResetProgress(wordIds: number[]) { return unwrap((await apiClient.post<ApiEnvelope<BatchResetResult>>('/words/batch/reset-progress', { word_ids: wordIds }, { headers: { 'Idempotency-Key': newEventId() } })).data) }
export async function exportWords(format: 'csv' | 'json', filters: WordFilters = {}) {
  const config: AxiosRequestConfig = { params: { ...filters, page: undefined, size: undefined, format }, responseType: 'blob', timeout: 60_000, paramsSerializer: { indexes: null } }
  const response = await apiClient.get<Blob>('/words/export', config)
  const url = URL.createObjectURL(response.data); const link = document.createElement('a')
  link.href = url; link.download = `words.${format}`; document.body.appendChild(link); link.click(); link.remove(); URL.revokeObjectURL(url)
}
