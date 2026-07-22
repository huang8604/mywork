import { apiClient, unwrap } from './client'
import type { ApiEnvelope, AuthUser, LoginPayload, PasswordChangePayload } from '@/types/domain'

export async function login(payload: LoginPayload) {
  return unwrap((await apiClient.post<ApiEnvelope<AuthUser>>('/auth/login', payload)).data)
}

export async function logout() {
  return unwrap((await apiClient.post<ApiEnvelope<{ ok: boolean }>>('/auth/logout')).data)
}

export async function fetchMe() {
  return unwrap((await apiClient.get<ApiEnvelope<AuthUser>>('/auth/me')).data)
}

export async function changePassword(payload: PasswordChangePayload) {
  return unwrap((await apiClient.post<ApiEnvelope<{ ok: boolean }>>('/auth/password', payload)).data)
}
