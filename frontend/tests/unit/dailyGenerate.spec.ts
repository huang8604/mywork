import { describe, expect, it } from 'vitest'
import { parseWordText } from '@/views/dailyGenerateLogic'

describe('parseWordText', () => {
  it('splits on newlines / commas (latin+CJK) / semicolons and dedupes case-insensitively', () => {
    expect(parseWordText('camera\nfocus, Camera\n  ')).toEqual(['camera', 'focus'])
  })
  it('preserves spaces inside phrases instead of splitting them into words', () => {
    expect(parseWordText('look forward to\ntake off, in front of')).toEqual(['look forward to', 'take off', 'in front of'])
  })
  it('drops blanks and # comment lines', () => {
    expect(parseWordText('# comment\n\n  \nword')).toEqual(['word'])
  })
  it('splits on CJK commas and semicolons too', () => {
    expect(parseWordText('苹果，香蕉；葡萄')).toEqual(['苹果', '香蕉', '葡萄'])
  })
})
