import { describe, expect, it } from 'vitest'
import { parseWordText } from '@/views/dailyGenerateLogic'

describe('parseWordText', () => {
  it('splits on newlines / commas (latin+CJK) / semicolons / whitespace and dedupes case-insensitively', () => {
    expect(parseWordText('camera\nfocus, Camera  focus\n  ')).toEqual(['camera', 'focus'])
  })
  it('drops blanks and # comment lines', () => {
    expect(parseWordText('# comment\n\n  \nword')).toEqual(['word'])
  })
  it('splits on CJK commas and semicolons too', () => {
    expect(parseWordText('苹果，香蕉；葡萄')).toEqual(['苹果', '香蕉', '葡萄'])
  })
})
