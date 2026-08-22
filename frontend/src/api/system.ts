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

export interface AudioProviderSettingsPayload {
  base_url: string
  api_key: string
  model: string
  voice: string
}

export async function saveAudioSettings(
  defaultProvider: AudioProvider,
  expectedVersion: number,
  providers: Partial<Record<AudioProvider, AudioProviderSettingsPayload>> = {},
) {
  return unwrap((await apiClient.put<ApiEnvelope<SystemAudioSettings>>('/system/audio-settings', {
    default_provider: defaultProvider,
    expected_version: expectedVersion,
    ...providers,
  })).data)
}

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
