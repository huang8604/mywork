import { describe, expect, it } from 'vitest'
import { allItemsAnswered, nextButtonLabel, nextButtonDisabled, summarize } from '@/views/reviewLogic'

describe('nextButtonLabel / nextButtonDisabled', () => {
  it('shows 下一题 when more cards remain', () => {
    expect(nextButtonLabel({ index: 2, total: 10 })).toBe('下一题')
    expect(nextButtonDisabled({ index: 2, total: 10 })).toBe(false)
  })
  it('shows 已完成 ✓ and disabled on the last card', () => {
    expect(nextButtonLabel({ index: 9, total: 10 })).toBe('已完成 ✓')
    expect(nextButtonDisabled({ index: 9, total: 10 })).toBe(true)
  })
  it('treats the empty round as finished', () => {
    expect(nextButtonLabel({ index: 0, total: 0 })).toBe('已完成 ✓')
    expect(nextButtonDisabled({ index: 0, total: 0 })).toBe(true)
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
  it('ignores unknown status values without throwing', () => {
    const results = new Map([
      [1, { status: 'known' }], [2, { status: 'weird' }],
    ])
    expect(summarize(results)).toEqual({ known: 1, unknown: 0, skipped: 0, total: 1 })
  })
})

describe('allItemsAnswered', () => {
  it('stays false until every session item has a valid result', () => {
    const results = new Map<number, { status: string }>([[11, { status: 'known' }]])
    expect(allItemsAnswered([11, 12], results)).toBe(false)
    results.set(12, { status: 'skipped' })
    expect(allItemsAnswered([11, 12], results)).toBe(true)
  })

  it('rejects empty sessions and invalid statuses', () => {
    expect(allItemsAnswered([], new Map())).toBe(false)
    expect(allItemsAnswered([11], new Map([[11, { status: 'invalid' }]]))).toBe(false)
  })
})
