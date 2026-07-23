import { describe, expect, it } from 'vitest'
import { actualCountEntries, requestedCountEntries, sessionWordCount } from '@/views/sessionCounts'
import type { PracticeSession } from '@/types/domain'

function session(actual_counts: Record<string, number>, requested_counts: Record<string, number> = {}): PracticeSession {
  return { actual_counts, requested_counts } as PracticeSession
}

describe('sessionWordCount', () => {
  it('uses unique_total for a self-selected list (10, not 20)', () => {
    // Regression: a 10-word selection stored {unique_total:10, selected:10};
    // summing every value double-counted to 20.
    expect(sessionWordCount(session({ unique_total: 10, selected: 10 }))).toBe(10)
  })

  it('sums category keys when unique_total is absent', () => {
    expect(sessionWordCount(session({ new: 5, error: 5, due: 5, custom: 5 }))).toBe(20)
  })

  it('ignores the selected meta-key when falling back to a sum', () => {
    expect(sessionWordCount(session({ selected: 7 }))).toBe(0)
  })

  it('is 0 for an empty map', () => {
    expect(sessionWordCount(session({}))).toBe(0)
  })
})

describe('requestedCountEntries', () => {
  it('labels a self-selection as 自选', () => {
    expect(requestedCountEntries(session({}, { selected: 10 }))).toEqual([{ label: '自选', value: 10 }])
  })

  it('labels category quotas in Chinese', () => {
    expect(requestedCountEntries(session({}, { new: 5, error: 5 }))).toEqual([
      { label: '新词', value: 5 },
      { label: '错词', value: 5 },
    ])
  })
})

describe('actualCountEntries', () => {
  it('drops the total and selected meta-keys from the breakdown', () => {
    expect(
      actualCountEntries(session({ unique_total: 20, selected: 20, new: 5, error: 5, due: 5, custom: 5 })),
    ).toEqual([
      { label: '新词', value: 5 },
      { label: '错词', value: 5 },
      { label: '到期', value: 5 },
      { label: '自定义', value: 5 },
    ])
  })

  it('is empty for a pure selection session (only meta-keys)', () => {
    expect(actualCountEntries(session({ unique_total: 10, selected: 10 }))).toEqual([])
  })
})
