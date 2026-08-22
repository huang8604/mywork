/** Weekday color + deer-mark theme for the worksheet and recitation exports. */
export interface WorksheetTheme {
  primary: string
  deep: string
  accent: string
  weekdayName: string
  icon: string
}

const ACCENT = '#fbbf24'

// Index = Date.getDay(): 0=Sunday … 6=Saturday.
const VIVID: WorksheetTheme[] = [
  { primary: '#7c3aed', deep: '#5b21b6', accent: ACCENT, weekdayName: '周日', icon: 'sun' },
  { primary: '#e11d48', deep: '#9f1239', accent: ACCENT, weekdayName: '周一', icon: 'mon' },
  { primary: '#ea580c', deep: '#9a3412', accent: ACCENT, weekdayName: '周二', icon: 'tue' },
  { primary: '#ca8a04', deep: '#854d0e', accent: ACCENT, weekdayName: '周三', icon: 'wed' },
  { primary: '#16a34a', deep: '#166534', accent: ACCENT, weekdayName: '周四', icon: 'thu' },
  { primary: '#0891b2', deep: '#155e75', accent: ACCENT, weekdayName: '周五', icon: 'fri' },
  { primary: '#2563eb', deep: '#1e3a8a', accent: ACCENT, weekdayName: '周六', icon: 'sat' },
]

/** Resolve the worksheet theme for an ISO date string (the session generated_at).
 *  Falls back to "today" when the date can't be parsed. */
export function worksheetTheme(dateStr: string | null | undefined): WorksheetTheme {
  const d = dateStr ? new Date(dateStr) : new Date()
  const idx = Number.isNaN(d.getTime()) ? new Date().getDay() : d.getDay()
  return VIVID[idx]
}
