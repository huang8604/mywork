import { apiClient, unwrap } from './client'
import type { ApiEnvelope, AudioProvider, DictionaryAudioProgress } from '@/types/domain'

export async function getDictionaryAudioProgress() {
  return unwrap((await apiClient.get<ApiEnvelope<DictionaryAudioProgress>>('/system/dictionary-audio/progress')).data)
}

export async function startDictionaryAudio(provider?: AudioProvider) {
  return unwrap((await apiClient.post<ApiEnvelope<DictionaryAudioProgress>>('/system/dictionary-audio/start', { provider: provider ?? null })).data)
}

export async function pauseDictionaryAudio() {
  return unwrap((await apiClient.post<ApiEnvelope<DictionaryAudioProgress>>('/system/dictionary-audio/pause')).data)
}

export async function resumeDictionaryAudio() {
  return unwrap((await apiClient.post<ApiEnvelope<DictionaryAudioProgress>>('/system/dictionary-audio/resume')).data)
}
