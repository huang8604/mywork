import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('@/api/auth', () => ({
  login: vi.fn(),
  logout: vi.fn(),
  fetchMe: vi.fn(),
  changePassword: vi.fn(),
}))

import * as authApi from '@/api/auth'
import { useAuthStore } from '@/stores/auth'

describe('auth store', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
  })

  it('fetchMe populates identity and marks initialized on success', async () => {
    ;(authApi.fetchMe as ReturnType<typeof vi.fn>).mockResolvedValue({
      username: 'admin', role: 'admin', actor_type: 'web_user',
    })
    const auth = useAuthStore()
    await auth.fetchMe()
    expect(auth.username).toBe('admin')
    expect(auth.role).toBe('admin')
    expect(auth.initialized).toBe(true)
    expect(auth.isLoggedIn).toBe(true)
  })

  it('fetchMe clears any stale identity on failure (e.g. 401)', async () => {
    ;(authApi.fetchMe as ReturnType<typeof vi.fn>).mockRejectedValue(new Error('unauthorized'))
    const auth = useAuthStore()
    auth.username = 'stale'
    await auth.fetchMe()
    expect(auth.username).toBeNull()
    expect(auth.role).toBeNull()
    expect(auth.initialized).toBe(true)
    expect(auth.isLoggedIn).toBe(false)
  })

  it('reset drops identity without a round-trip (used by the 401 interceptor)', () => {
    const auth = useAuthStore()
    auth.username = 'someone'
    auth.role = 'admin'
    auth.reset()
    expect(auth.username).toBeNull()
    expect(auth.role).toBeNull()
    expect(auth.initialized).toBe(true)
  })

  it('login stores the returned identity', async () => {
    ;(authApi.login as ReturnType<typeof vi.fn>).mockResolvedValue({
      username: 'stu', role: 'student', actor_type: 'web_user',
    })
    const auth = useAuthStore()
    const me = await auth.login('stu', 'pw')
    expect(me.role).toBe('student')
    expect(auth.role).toBe('student')
    expect(auth.username).toBe('stu')
    expect(auth.initialized).toBe(true)
  })

  it('logout clears the identity even if the call throws', async () => {
    ;(authApi.logout as ReturnType<typeof vi.fn>).mockRejectedValue(new Error('boom'))
    const auth = useAuthStore()
    auth.username = 'admin'
    auth.role = 'admin'
    await auth.logout()
    expect(auth.username).toBeNull()
    expect(auth.role).toBeNull()
  })
})
