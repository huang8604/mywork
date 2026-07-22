import { describe, expect, it } from 'vitest'
import { nextButtonLabel, nextButtonDisabled, summarize } from '@/views/reviewLogic'

describe('nextButtonLabel / nextButtonDisabled', () => {
  it('shows 下一题 when more cards remain', () => {
    expect(nextButtonLabel({ index: 2, total: 10, revealed: true })).toBe('下一题')
    expect(nextButtonDisabled({ index: 2, total: 10 })).toBe(false)
  })
  it('shows 已完成 ✓ and disabled on the last card', () => {
    expect(nextButtonLabel({ index: 9, total: 10, revealed: true })).toBe('已完成 ✓')
    expect(nextButtonDisabled({ index: 9, total: 10 })).toBe(true)
  })
})

describe('summarize', () => {
  it('counts known/unknown/skipped from a results map', () => {
    const results = new Map([
      [1, { status: 'known' }], [2, { status: 'unknown' }],
      [3, { status: 'skipped' }], [4, { status: 'known' }],
    ])
    expect(summarize(results)).toEqual({ known: 2, unknown: 1, skipped: 1, total: 4 })
  })
})
