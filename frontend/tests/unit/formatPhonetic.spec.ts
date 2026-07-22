import { describe, expect, it } from 'vitest'
import { formatPhonetic } from '@/utils/formatPhonetic'

describe('formatPhonetic', () => {
  it('wraps a phonetic in slashes', () => {
    expect(formatPhonetic('ˈkæmərə')).toBe('/ˈkæmərə/')
  })
  it('returns empty string for null/empty so cells stay blank (no slashes)', () => {
    expect(formatPhonetic(null)).toBe('')
    expect(formatPhonetic('')).toBe('')
    expect(formatPhonetic(undefined)).toBe('')
  })
  it('trims whitespace and strips existing surrounding slashes (no double-wrap)', () => {
    expect(formatPhonetic('  /ə/  ')).toBe('/ə/')
  })
})
