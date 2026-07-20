import { apiClient, unwrap } from './client'
import type { ApiEnvelope, Capabilities } from '@/types/domain'
export async function getCapabilities(signal?: AbortSignal) { return unwrap((await apiClient.get<ApiEnvelope<Capabilities>>('/capabilities', { signal })).data) }
