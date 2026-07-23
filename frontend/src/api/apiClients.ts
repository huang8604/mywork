import { apiClient, unwrap } from './client'
import type {
  ApiClient,
  ApiClientCreatePayload,
  ApiClientCreated,
  ApiClientUpdatePayload,
  ApiEnvelope,
} from '@/types/domain'

export async function listApiClients() {
  return unwrap((await apiClient.get<ApiEnvelope<ApiClient[]>>('/api-clients')).data)
}

export async function createApiClient(payload: ApiClientCreatePayload) {
  return unwrap((await apiClient.post<ApiEnvelope<ApiClientCreated>>('/api-clients', payload)).data)
}

export async function rotateApiToken(id: number) {
  return unwrap((await apiClient.post<ApiEnvelope<{ token: string }>>(`/api-clients/${id}/tokens`)).data)
}

export async function updateApiClient(id: number, payload: ApiClientUpdatePayload) {
  return unwrap((await apiClient.patch<ApiEnvelope<ApiClient>>(`/api-clients/${id}`, payload)).data)
}

export async function disableApiClient(id: number) {
  await apiClient.delete(`/api-clients/${id}`)
}

export async function deleteApiClient(id: number) {
  await apiClient.delete(`/api-clients/${id}/permanent`)
}

export async function revokeApiToken(id: number, tokenId: number) {
  await apiClient.delete(`/api-clients/${id}/tokens/${tokenId}`)
}
