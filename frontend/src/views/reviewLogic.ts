export interface ReviewSummary {
  known: number
  unknown: number
  skipped: number
  total: number
}

/**
 * Label for the primary 下一题 button in the locked (revealed) state.
 * On the last card (or when there are no cards) it becomes a 已完成 ✓ marker.
 */
export function nextButtonLabel(state: { index: number; total: number; revealed: boolean }): string {
  return isLast(state) ? '已完成 ✓' : '下一题'
}

/**
 * The primary 下一题 button is disabled on the last card (nothing to advance to).
 */
export function nextButtonDisabled(state: { index: number; total: number }): boolean {
  return isLast(state)
}

/**
 * Tally in-memory results into known/unknown/skipped/total counts for the
 * read-only finish summary. Unknown status values simply aren't counted.
 */
export function summarize(results: Map<number, { status: string }>): ReviewSummary {
  let known = 0
  let unknown = 0
  let skipped = 0
  for (const r of results.values()) {
    if (r.status === 'known') known++
    else if (r.status === 'unknown') unknown++
    else if (r.status === 'skipped') skipped++
  }
  return { known, unknown, skipped, total: known + unknown + skipped }
}

function isLast(s: { index: number; total: number }): boolean {
  return s.total <= 0 || s.index >= s.total - 1
}
