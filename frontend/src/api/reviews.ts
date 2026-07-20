import { apiClient, unwrap } from './client'
import type { ApiEnvelope, ReviewFilters, ReviewLog, ReviewStatus } from '@/types/domain'

export async function listReviews(filters: ReviewFilters = {}, signal?: AbortSignal) {
  const response = await apiClient.get<ApiEnvelope<ReviewLog[]>>('/reviews', { params: filters, signal })
  return { data: response.data.data, meta: response.data.meta, requestId: response.data.request_id }
}
export async function correctReview(review: ReviewLog, status: ReviewStatus) {
  return unwrap((await apiClient.patch<ApiEnvelope<ReviewLog>>(`/reviews/${review.id}`, {
    status, client_event_id: review.client_event_id, expected_version: review.version,
    reviewed_at: review.reviewed_at, duration_ms: review.duration_ms,
  })).data)
}
export async function listAllRoundReviews(roundId: number, signal?: AbortSignal) {
  const reviews: ReviewLog[] = []; let page = 1
  do {
    const response = await listReviews({ round_id: roundId, page, size: 100, sort: 'reviewed_at_asc' }, signal)
    reviews.push(...response.data)
    const total = Number(response.meta.total)
    if (response.data.length < 100 || (Number.isFinite(total) && reviews.length >= total)) break
    page += 1
  } while (true)
  return reviews
}
