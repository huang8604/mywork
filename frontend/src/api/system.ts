import { apiClient, unwrap } from './client'
import type { ApiEnvelope, AudioProvider, DictionaryAudioProgress, SystemAudioSettings, SystemIssueNote } from '@/types/domain'

export async function getIssueNote() {
  return unwrap((await apiClient.get<ApiEnvelope<SystemIssueNote>>('/system/issue-notes')).data)
}

export async function saveIssueNote(content: string, expectedVersion: number) {
  return unwrap((await apiClient.put<ApiEnvelope<SystemIssueNote>>('/system/issue-notes', { content, expected_version: expectedVersion })).data)
}

export async function getAudioSettings() {
  return unwrap((await apiClient.get<ApiEnvelope<SystemAudioSettings>>('/system/audio-settings')).data)
}

export type AudioProviderDraft = { base_url: string; api_key: string }

export async function saveAudioSettings(
  defaultProvider: AudioProvider,
  providers: { mimo: AudioProviderDraft; volc: AudioProviderDraft },
  expectedVersion: number,
  autoGenerateOnImport?: boolean,
) {
  return unwrap((await apiClient.put<ApiEnvelope<SystemAudioSettings>>('/system/audio-settings', {
    default_provider: defaultProvider,
    mimo: providers.mimo,
    volc: providers.volc,
    expected_version: expectedVersion,
    auto_generate_on_import: autoGenerateOnImport ?? null,
  })).data)
}

export async function testAudioSettings(provider: AudioProvider) {
  const response = await apiClient.post('/system/audio-settings/test', { provider }, { responseType: 'blob' })
  return {
    blob: response.data as Blob,
    provider: String(response.headers['x-tts-provider'] || ''),
    model: String(response.headers['x-tts-model'] || ''),
    voice: String(response.headers['x-tts-voice'] || ''),
  }
}

export async function getDictionaryAudioProgress() {
  return unwrap((await apiClient.get<ApiEnvelope<DictionaryAudioProgress>>('/system/dictionary-audio/progress')).data)
}

export async function startDictionaryAudio(provider?: AudioProvider, force = false) {
  return unwrap((await apiClient.post<ApiEnvelope<DictionaryAudioProgress>>('/system/dictionary-audio/start', { provider: provider ?? null, force })).data)
}

export async function pauseDictionaryAudio() {
  return unwrap((await apiClient.post<ApiEnvelope<DictionaryAudioProgress>>('/system/dictionary-audio/pause')).data)
}

export async function resumeDictionaryAudio() {
  return unwrap((await apiClient.post<ApiEnvelope<DictionaryAudioProgress>>('/system/dictionary-audio/resume')).data)
}
