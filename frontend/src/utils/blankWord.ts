export interface BlankWordResult { text: string; found: boolean }

export function escapeRegExp(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
}

export function blankWord(sentence: string | null | undefined, word: string): BlankWordResult {
  if (!sentence || !word.trim()) return { text: sentence || '', found: false }
  const escaped = escapeRegExp(word.trim())
  const pattern = new RegExp(`(?<![\\p{L}\\p{N}_])${escaped}(?![\\p{L}\\p{N}_])`, 'giu')
  let found = false
  const text = sentence.replace(pattern, () => { found = true; return '_____' })
  return { text, found }
}
