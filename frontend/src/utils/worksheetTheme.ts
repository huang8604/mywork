/** Weekday color theme for the worksheet + recitation exports.
 *
 *  Seven Morandi (low-saturation) palettes — one per day, Sunday…Saturday —
 *  each a {primary, deep} pair with a shared muted-gold accent. The worksheet
 *  hero gradient + table header use the day's `primary`/`deep`; the gold
 *  `accent` is the hero border-bottom highlight. The day is read from the
 *  session's `generated_at` so a sheet keeps its color regardless of when it's
 *  printed. */
export interface WorksheetTheme {
  primary: string
  deep: string
  accent: string
  weekdayName: string
}

const ACCENT = '#c2a370'

// Index = Date.getDay(): 0=Sunday … 6=Saturday.
const MORANDI: WorksheetTheme[] = [
  { primary: '#856b94', deep: '#685276', accent: ACCENT, weekdayName: '周日' }, // Sun
  { primary: '#a85a5a', deep: '#874a4a', accent: ACCENT, weekdayName: '周一' }, // Mon
  { primary: '#a9744f', deep: '#855c3d', accent: ACCENT, weekdayName: '周二' }, // Tue
  { primary: '#9c8a4e', deep: '#7c6d3b', accent: ACCENT, weekdayName: '周三' }, // Wed
  { primary: '#6f8a66', deep: '#556d4f', accent: ACCENT, weekdayName: '周四' }, // Thu
  { primary: '#5e8787', deep: '#476a6a', accent: ACCENT, weekdayName: '周五' }, // Fri
  { primary: '#5e7691', deep: '#475d74', accent: ACCENT, weekdayName: '周六' }, // Sat
]

/** Resolve the worksheet theme for an ISO date string (the session generated_at).
 *  Falls back to "today" when the date can't be parsed. */
export function worksheetTheme(dateStr: string | null | undefined): WorksheetTheme {
  const d = dateStr ? new Date(dateStr) : new Date()
  const idx = Number.isNaN(d.getTime()) ? new Date().getDay() : d.getDay()
  return MORANDI[idx]
}
