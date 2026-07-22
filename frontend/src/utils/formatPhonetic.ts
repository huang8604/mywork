/** Wrap a phonetic in slashes for display; empty input → empty string (blank cell, no slashes). */
export function formatPhonetic(phonetic: string | null | undefined): string {
  if (!phonetic) return ''
  const trimmed = phonetic.trim().replace(/^\/+|\/+$/g, '')
  if (!trimmed) return ''
  return `/${trimmed}/`
}
