import deerMon from '@/assets/deer-mon.png'
import deerTue from '@/assets/deer-tue.png'
import deerWed from '@/assets/deer-wed.png'
import deerThu from '@/assets/deer-thu.png'
import deerFri from '@/assets/deer-fri.png'
import deerSat from '@/assets/deer-sat.png'

/** Six supplied illustrations; Sunday intentionally reuses Monday's image. */
export const deerAssets: Record<string, string> = {
  mon: deerMon,
  tue: deerTue,
  wed: deerWed,
  thu: deerThu,
  fri: deerFri,
  sat: deerSat,
  sun: deerMon,
}

export function deerAsset(variant: string | undefined, fallback = 'mon'): string {
  return deerAssets[variant || fallback] || deerAssets[fallback]
}
