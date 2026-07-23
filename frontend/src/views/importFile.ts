export function createInlineImportFile(text: string): File {
  const content = text.trim()
  const jsonLike = content.startsWith('[') || content.startsWith('{')
  return new File(
    [content],
    jsonLike ? 'words.json' : 'words.txt',
    { type: jsonLike ? 'application/json' : 'text/plain' },
  )
}
