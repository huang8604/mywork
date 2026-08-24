import { apiClient, unwrap } from './client'
import type { ApiEnvelope, ContributionsSummary, RecentErrorWords, StatsSummary } from '@/types/domain'
export async function getStatsSummary(signal?: AbortSignal) { return unwrap((await apiClient.get<ApiEnvelope<StatsSummary>>('/stats/summary', { signal })).data) }
export async function getContributions(signal?: AbortSignal) { return unwrap((await apiClient.get<ApiEnvelope<ContributionsSummary>>('/stats/contributions', { signal })).data) }
export async function getOwnStatsSummary(signal?: AbortSignal) { return unwrap((await apiClient.get<ApiEnvelope<StatsSummary>>('/stats/my-summary', { signal })).data) }
export async function getOwnContributions(signal?: AbortSignal) { return unwrap((await apiClient.get<ApiEnvelope<ContributionsSummary>>('/stats/my-contributions', { signal })).data) }
export async function getRecentErrors(signal?: AbortSignal) { return unwrap((await apiClient.get<ApiEnvelope<RecentErrorWords>>('/stats/my-recent-errors', { signal })).data) }
