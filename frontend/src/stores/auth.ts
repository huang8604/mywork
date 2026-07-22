import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import type { AuthUser, WebRole } from '@/types/domain'
import * as authApi from '@/api/auth'

export const useAuthStore = defineStore('auth', () => {
  const username = ref<string | null>(null)
  const role = ref<WebRole | null>(null)
  // Whether we have attempted fetchMe at least once this session. The router
  // guard awaits fetchMe() on the first navigation before deciding a redirect.
  const initialized = ref(false)

  const isLoggedIn = computed(() => username.value !== null)

  async function fetchMe() {
    try {
      const me: AuthUser = await authApi.fetchMe()
      username.value = me.username
      role.value = me.role
    } catch {
      username.value = null
      role.value = null
    } finally {
      initialized.value = true
    }
  }

  async function login(user: string, password: string) {
    const me: AuthUser = await authApi.login({ username: user, password })
    username.value = me.username
    role.value = me.role
    initialized.value = true
    return me
  }

  async function logout() {
    // Best-effort: clear the local identity even if the network call fails so
    // the UI always returns to the login page.
    try {
      await authApi.logout()
    } catch {
      // ignore — we are discarding the session regardless
    }
    username.value = null
    role.value = null
  }

  /** Drop the cached identity without a round-trip (used by the 401 interceptor). */
  function reset() {
    username.value = null
    role.value = null
    initialized.value = true
  }

  return { username, role, initialized, isLoggedIn, fetchMe, login, logout, reset }
})
