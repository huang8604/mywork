import { describe, expect, it } from 'vitest'
import { createInlineImportFile } from '@/views/importFile'

const readFile = (file: File) => new Promise<string>((resolve, reject) => {
  const reader = new FileReader()
  reader.onerror = () => reject(reader.error)
  reader.onload = () => resolve(String(reader.result))
  reader.readAsText(file)
})

describe('createInlineImportFile', () => {
  it('uploads a pasted JSON template as a JSON file', async () => {
    const template = JSON.stringify([{ en_word: 'example', cn_meaning: '示例', tags: [] }])
    const file = createInlineImportFile(template)

    expect(file.name).toBe('words.json')
    expect(file.type).toBe('application/json')
    expect(await readFile(file)).toBe(template)
  })

  it('keeps a plain English word list as TXT', async () => {
    const file = createInlineImportFile('camera\nfocus')

    expect(file.name).toBe('words.txt')
    expect(file.type).toBe('text/plain')
    expect(await readFile(file)).toBe('camera\nfocus')
  })
})
