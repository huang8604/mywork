const enabled = import.meta.env.DEV || import.meta.env.VITE_DEBUG_LOGS === 'true'

export function debugLog(event: string, details: Record<string, unknown>): void {
  if (!enabled) return
  console.debug(`[word-memory] ${event}`, details)
}
