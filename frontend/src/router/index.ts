import { nextTick } from 'vue'
import { createRouter, createWebHistory, type RouteRecordRaw } from 'vue-router'
import AppShell from '@/layouts/AppShell.vue'
import { useAuthStore } from '@/stores/auth'
import type { WebRole } from '@/types/domain'

export interface NavMeta {
  label: string
  shortLabel: string
  icon: string
  nav?: boolean
  title?: string
  /** Roles allowed to view/use this route. Undefined = any authenticated user. */
  roles?: WebRole[]
}

function defaultPath(role: WebRole | null): string {
  return role === 'student' ? '/review' : '/dashboard'
}

export const routes: RouteRecordRaw[] = [
  { path: '/', redirect: '/dashboard' },
  {
    path: '/login',
    name: 'login',
    component: () => import('@/views/LoginView.vue'),
    meta: { title: '登录' },
  },
  {
    path: '/', component: AppShell,
    children: [
      { path: 'dashboard', name: 'dashboard', component: () => import('@/views/DashboardView.vue'), meta: { label: '概览', shortLabel: '概览', icon: '⌂', nav: true, title: '今日概览', roles: ['admin'] } },
      { path: 'words', name: 'words', component: () => import('@/views/WordsView.vue'), meta: { label: '单词库', shortLabel: '词库', icon: 'Aa', nav: true, title: '单词库', roles: ['admin'] } },
      { path: 'review', name: 'review', component: () => import('@/views/ReviewView.vue'), meta: { label: '在线复习', shortLabel: '复习', icon: '◫', nav: true, title: '在线复习', roles: ['admin', 'student'] } },
      { path: 'daily/generate', name: 'daily-generate', component: () => import('@/views/DailyGenerateView.vue'), meta: { label: '复习表', shortLabel: '复习表', icon: '▤', nav: true, title: '复习表', roles: ['admin'] } },
      { path: 'daily/sessions/:id', name: 'practice-session', component: () => import('@/views/PracticeSessionView.vue'), meta: { label: '复习回录', shortLabel: '回录', icon: '✓', title: '复习结果回录', roles: ['admin'] } },
      { path: 'history', name: 'history', component: () => import('@/views/HistoryView.vue'), meta: { label: '复习历史', shortLabel: '历史', icon: '↺', title: '复习历史', roles: ['admin'] } },
      { path: 'users', name: 'users', component: () => import('@/views/UsersView.vue'), meta: { label: '用户管理', shortLabel: '用户', icon: '◐', title: '用户管理', roles: ['admin'] } },
      { path: 'system', name: 'system', component: () => import('@/views/SystemView.vue'), meta: { label: '系统管理', shortLabel: '系统', icon: '⚙', nav: true, title: '系统管理', roles: ['admin'] } },
      { path: ':pathMatch(.*)*', name: 'not-found', component: () => import('@/views/NotFoundView.vue'), meta: { label: '页面不存在', shortLabel: '404', icon: '?', title: '页面不存在' } },
    ],
  },
]

const router = createRouter({ history: createWebHistory(), routes, scrollBehavior: () => ({ top: 0 }) })

router.beforeEach(async (to) => {
  const auth = useAuthStore()
  if (!auth.initialized) {
    await auth.fetchMe()
  }
  if (to.path === '/login') {
    // Already signed in? Skip the login page and go to the role's home.
    if (auth.role) return { path: defaultPath(auth.role), replace: true }
    return true
  }
  const allowedRoles = to.meta.roles as WebRole[] | undefined
  if (!auth.role || (allowedRoles && !allowedRoles.includes(auth.role))) {
    return {
      path: '/login',
      query: to.fullPath && to.fullPath !== '/' ? { redirect: to.fullPath } : undefined,
    }
  }
  return true
})

router.afterEach((to, from) => {
  document.title = `${String(to.meta.title || to.meta.label || '拾词')} · 单词记忆`
  if (from.matched.length) {
    nextTick(() => document.querySelector<HTMLElement>('#main-content')?.focus({ preventScroll: true }))
  }
})
export default router
