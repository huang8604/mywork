import { describe, expect, it } from 'vitest'
import { worksheetTheme } from '@/utils/worksheetTheme'

describe('worksheetTheme', () => {
  it('maps Monday (2026-07-20) to the vivid red palette', () => {
    const t = worksheetTheme('2026-07-20T00:00:00Z')
    expect(t.weekdayName).toBe('周一')
    expect(t.primary).toBe('#e11d48')
    expect(t.accent).toBe('#fbbf24')
    expect(t.icon).toBe('mon')
    expect(t.weekdayIndex).toBe(1)
  })

  it('numbers the whole week Monday-first for the header fawn position', () => {
    const days = ['2026-07-20', '2026-07-21', '2026-07-22', '2026-07-23', '2026-07-24', '2026-07-25', '2026-07-26']
    const indexes = days.map(d => worksheetTheme(`${d}T00:00:00Z`).weekdayIndex)
    expect(indexes).toEqual([1, 2, 3, 4, 5, 6, 7])
  })

  it('maps Saturday (2026-07-25) to the vivid blue palette', () => {
    const t = worksheetTheme('2026-07-25T00:00:00Z')
    expect(t.weekdayName).toBe('周六')
    expect(t.primary).toBe('#2563eb')
  })

  it('maps Sunday (2026-07-26) to the vivid purple palette', () => {
    expect(worksheetTheme('2026-07-26T00:00:00Z').weekdayName).toBe('周日')
    expect(worksheetTheme('2026-07-26T00:00:00Z').primary).toBe('#7c3aed')
  })

  it('cycles through all seven distinct primaries over a week', () => {
    const days = ['2026-07-20', '2026-07-21', '2026-07-22', '2026-07-23', '2026-07-24', '2026-07-25', '2026-07-26']
    const primaries = days.map(d => worksheetTheme(`${d}T00:00:00Z`).primary)
    expect(new Set(primaries).size).toBe(7)
  })

  it('falls back to today on an unparseable date without throwing', () => {
    const t = worksheetTheme('not-a-date')
    expect(t.primary).toMatch(/^#[0-9a-f]{6}$/)
  })
})
