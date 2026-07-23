/** Helpers for rendering a PracticeSession's requested/actual count maps.
 *
 *  The backend stores `actual_counts` as a MIX of a total (`unique_total`) plus
 *  per-category breakdowns (`new`/`error`/`due`/`custom`, or `selected` for an
 *  explicit word list). Naively summing every value double-counts, and the raw
 *  keys are English. These helpers resolve both: one canonical word count, and
 *  labelled breakdown entries with the meta-keys stripped. */
import type { PracticeSession } from '@/types/domain'

export const SESSION_COUNT_LABELS: Record<string, string> = {
  new: '新词',
  error: '错词',
  due: '到期',
  custom: '自定义',
  selected: '自选',
  unique_total: '总词数',
  new_words: '新词',
  error_words: '错词',
  due_words: '到期',
  custom_words: '自定义',
}

/** Keys that are aggregates, not categories — never shown as a breakdown chip. */
const META_KEYS = new Set(['unique_total', 'selected'])

export interface CountEntry {
  label: string
  value: number
}

/** The single canonical number of words in the session.
 *  Prefers `unique_total`; otherwise sums the category keys (meta-keys excluded)
 *  so a `{unique_total:10, selected:10}` selection session reads 10, not 20. */
export function sessionWordCount(session: PracticeSession): number {
  const counts = (session.actual_counts || {}) as Record<string, number>
  if (typeof counts.unique_total === 'number') return counts.unique_total
  let sum = 0
  for (const [key, value] of Object.entries(counts)) {
    if (META_KEYS.has(key)) continue
    sum += Number(value) || 0
  }
  return sum
}

function toEntries(raw: Record<string, number> | undefined, dropMeta: boolean): CountEntry[] {
  const out: CountEntry[] = []
  for (const [key, value] of Object.entries(raw || {})) {
    if (dropMeta && META_KEYS.has(key)) continue
    out.push({ label: SESSION_COUNT_LABELS[key] || key, value: Number(value) || 0 })
  }
  return out
}

/** Labelled breakdown of what was requested (categories, or 自选 for a list). */
export function requestedCountEntries(session: PracticeSession): CountEntry[] {
  return toEntries(session.requested_counts, false)
}

/** Labelled per-category breakdown of what actually made it in. Meta-keys
 *  (`unique_total`/`selected`) are dropped — show `sessionWordCount` for the
 *  total. Empty for a pure selection session (only the total exists). */
export function actualCountEntries(session: PracticeSession): CountEntry[] {
  return toEntries(session.actual_counts, true)
}
