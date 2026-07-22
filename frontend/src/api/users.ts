import { apiClient, unwrap } from './client'
import type { ApiEnvelope, UserCreatePayload, UserUpdatePayload, WebUser } from '@/types/domain'

export async function listUsers() {
  return unwrap((await apiClient.get<ApiEnvelope<WebUser[]>>('/users')).data)
}

export async function createUser(payload: UserCreatePayload) {
  return unwrap((await apiClient.post<ApiEnvelope<WebUser>>('/users', payload)).data)
}

export async function updateUser(id: number, payload: UserUpdatePayload) {
  return unwrap((await apiClient.patch<ApiEnvelope<WebUser>>(`/users/${id}`, payload)).data)
}

export async function resetUserPassword(id: number, newPassword: string) {
  return unwrap(
    (await apiClient.post<ApiEnvelope<{ ok: boolean }>>(`/users/${id}/password`, {
      new_password: newPassword,
    })).data,
  )
}

export async function deleteUser(id: number) {
  await apiClient.delete(`/users/${id}`)
}
