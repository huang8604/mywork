import { apiClient, unwrap } from './client'
import type { ApiEnvelope, StatsSummary } from '@/types/domain'
export async function getStatsSummary(signal?: AbortSignal) { return unwrap((await apiClient.get<ApiEnvelope<StatsSummary>>('/stats/summary', { signal })).data) }
