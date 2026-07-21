import { AxiosError, AxiosHeaders } from 'axios'
import { describe, expect, it } from 'vitest'
import { ApiError, newEventId, normalizeApiError, unwrap } from '@/api/client'

describe('API client contract handling', () => {
  it('unwraps JSON envelopes but retains conflict details and request ids in errors', () => {
    expect(unwrap({ code: 'OK', message: 'success', data: { id: 7 }, meta: {}, request_id: 'req-ok' })).toEqual({ id: 7 })
    const error = new AxiosError('conflict', 'ERR_BAD_REQUEST', undefined, undefined, {
      status: 409, statusText: 'Conflict', headers: new AxiosHeaders(), config: { headers: new AxiosHeaders() },
      data: { code: 'VERSION_CONFLICT', message: 'session was modified', details: [{ current_version: 3 }], request_id: 'req-conflict' },
    })
    const normalized = normalizeApiError(error)
    expect(normalized).toBeInstanceOf(ApiError)
    expect(normalized.isConflict).toBe(true)
    expect(normalized.requestId).toBe('req-conflict')
    expect(normalized.details[0].current_version).toBe(3)
  })

  it('maps timeout and cancellation into recoverable errors', () => {
    expect(normalizeApiError(new AxiosError('timeout', 'ECONNABORTED')).message).toContain('超时')
    expect(normalizeApiError(new AxiosError('cancel', 'ERR_CANCELED')).isCanceled).toBe(true)
  })

  it('generates a UUID when randomUUID is unavailable in an insecure HTTP context', () => {
    const originalCrypto = globalThis.crypto
    let nextByte = 0
    Object.defineProperty(globalThis, 'crypto', {
      value: {
        getRandomValues<T extends ArrayBufferView>(array: T): T {
          const bytes = new Uint8Array(array.buffer, array.byteOffset, array.byteLength)
          bytes.forEach((_, index) => { bytes[index] = nextByte++ })
          return array
        },
      },
      configurable: true,
    })

    try {
      expect(newEventId()).toMatch(/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/)
    } finally {
      Object.defineProperty(globalThis, 'crypto', { value: originalCrypto, configurable: true })
    }
  })
})
