import type { ApiScope } from '@/types/domain'
import { ALL_API_SCOPES } from '@/types/domain'

/**
 * Map an API scope to a short Chinese label for display in tables/checkboxes.
 * Unknown scopes fall back to the raw string.
 */
export function scopeLabel(scope: string): string {
  const labels: Record<ApiScope, string> = {
    'words:read': '词库·读',
    'words:write': '词库·写',
    'words:export': '词库·导出',
    'practice:generate': '复习表·生成',
    'practice:read': '复习表·读',
    'practice:write': '复习表·写',
    'reviews:write': '复习·写',
    'reviews:read': '复习·读',
  }
  return (labels as Record<string, string>)[scope] ?? scope
}

/** Return only known scopes (drops anything not in the canonical ALL_API_SCOPES). */
export function scopesForDisplay(scopes: string[]): string[] {
  const known = new Set<string>(ALL_API_SCOPES)
  return scopes.filter((s) => known.has(s))
}
