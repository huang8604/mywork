import { describe, expect, it } from 'vitest'
import { worksheetTheme } from '@/utils/worksheetTheme'

describe('worksheetTheme', () => {
  it('maps Monday (2026-07-20) to the red palette', () => {
    const t = worksheetTheme('2026-07-20T00:00:00Z')
    expect(t.weekdayName).toBe('周一')
    expect(t.primary).toBe('#a85a5a')
    expect(t.accent).toBe('#c2a370')
  })

  it('maps Saturday (2026-07-25) to the dusty-blue palette', () => {
    const t = worksheetTheme('2026-07-25T00:00:00Z')
    expect(t.weekdayName).toBe('周六')
    expect(t.primary).toBe('#5e7691')
  })

  it('maps Sunday (2026-07-26) to the mauve palette', () => {
    expect(worksheetTheme('2026-07-26T00:00:00Z').weekdayName).toBe('周日')
    expect(worksheetTheme('2026-07-26T00:00:00Z').primary).toBe('#856b94')
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
