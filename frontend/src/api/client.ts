import axios, { AxiosError } from 'axios'
import type { ApiEnvelope, ApiErrorBody } from '@/types/domain'
import { debugLog } from '@/utils/debugLog'

const errorMessages: Record<number, string> = {
  400: '请求内容不正确', 401: '登录状态已失效，请重新登录', 403: '当前账号没有操作权限',
  404: '没有找到对应数据', 409: '数据已被修改，请刷新后重试', 413: '上传文件过大',
  422: '请检查填写内容', 429: '操作过于频繁，请稍后重试', 500: '服务器暂时不可用',
  502: '服务连接失败', 503: '服务繁忙，请稍后重试', 504: '服务响应超时',
}

export class ApiError extends Error {
  constructor(
    message: string,
    public readonly status?: number,
    public readonly code = 'NETWORK_ERROR',
    public readonly requestId?: string,
    public readonly details: ApiErrorBody['details'] = [],
  ) { super(message); this.name = 'ApiError' }
  get isConflict() { return this.status === 409 }
  get isCanceled() { return this.code === 'REQUEST_CANCELED' }
}

export const apiClient = axios.create({ baseURL: '/api/v1', timeout: 15_000 })

apiClient.interceptors.request.use((config) => {
  debugLog('api.request', { method: config.method?.toUpperCase(), url: config.url })
  return config
})

apiClient.interceptors.response.use(
  (response) => {
    debugLog('api.response', {
      method: response.config.method?.toUpperCase(),
      url: response.config.url,
      status: response.status,
      requestId: response.headers['x-request-id'] || response.data?.request_id,
    })
    return response
  },
  (error: AxiosError<ApiErrorBody>) => {
    const normalized = normalizeApiError(error)
    debugLog('api.error', {
      method: error.config?.method?.toUpperCase(),
      url: error.config?.url,
      status: normalized.status,
      code: normalized.code,
      requestId: normalized.requestId,
    })
    return Promise.reject(normalized)
  },
)

export function normalizeApiError(error: unknown): ApiError {
  if (axios.isCancel(error) || (error instanceof AxiosError && error.code === 'ERR_CANCELED')) {
    return new ApiError('请求已取消', undefined, 'REQUEST_CANCELED')
  }
  if (error instanceof ApiError) return error
  if (error instanceof AxiosError) {
    const status = error.response?.status
    const body = error.response?.data
    const message = body?.message || (status ? errorMessages[status] : undefined) || (error.code === 'ECONNABORTED' ? '请求超时，请重试' : '网络连接失败，请检查网络')
    return new ApiError(message, status, body?.code, body?.request_id || error.response?.headers['x-request-id'], body?.details)
  }
  return new ApiError(error instanceof Error ? error.message : '发生未知错误')
}

export function unwrap<T>(value: ApiEnvelope<T>): T { return value.data }
export function requestId(value: ApiEnvelope<unknown>): string { return value.request_id }
export function newEventId(): string {
  const webCrypto = globalThis.crypto
  if (typeof webCrypto?.randomUUID === 'function') return webCrypto.randomUUID()

  const bytes = new Uint8Array(16)
  if (typeof webCrypto?.getRandomValues === 'function') {
    webCrypto.getRandomValues(bytes)
  } else {
    for (let index = 0; index < bytes.length; index += 1) bytes[index] = Math.floor(Math.random() * 256)
  }
  bytes[6] = (bytes[6] & 0x0f) | 0x40
  bytes[8] = (bytes[8] & 0x3f) | 0x80
  const hex = Array.from(bytes, byte => byte.toString(16).padStart(2, '0')).join('')
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`
}
