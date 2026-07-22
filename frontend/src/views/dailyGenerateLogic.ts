/** Split a blob of words on newlines / latin & CJK commas / semicolons / whitespace;
 *  drop blanks and '#' comment lines; dedupe case-insensitively (first wins).
 *
 *  Lines whose first non-whitespace character is '#' are treated as comments and
 *  skipped in full (so "# note: ..." never leaks its words into the output). Each
 *  remaining line is then tokenised on the comma/semicolon/whitespace separators
 *  so users can also write "camera, focus" on a single line. */
export function parseWordText(raw: string): string[] {
  const seen = new Set<string>()
  const out: string[] = []
  for (const line of raw.split(/[\r\n]+/)) {
    const lineTrimmed = line.trim()
    if (!lineTrimmed || lineTrimmed.startsWith('#')) continue
    for (const token of line.split(/[\s,，;；]+/)) {
      const w = token.trim()
      if (!w || w.startsWith('#')) continue
      const key = w.toLowerCase()
      if (seen.has(key)) continue
      seen.add(key)
      out.push(w)
    }
  }
  return out
}
