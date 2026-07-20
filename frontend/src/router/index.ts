import { nextTick } from 'vue'
import { createRouter, createWebHistory, type RouteRecordRaw } from 'vue-router'
import AppShell from '@/layouts/AppShell.vue'

export interface NavMeta { label: string; shortLabel: string; icon: string; nav?: boolean; title?: string }

export const routes: RouteRecordRaw[] = [
  { path: '/', redirect: '/dashboard' },
  {
    path: '/', component: AppShell,
    children: [
      { path: 'dashboard', name: 'dashboard', component: () => import('@/views/DashboardView.vue'), meta: { label: '概览', shortLabel: '概览', icon: '⌂', nav: true, title: '今日概览' } },
      { path: 'words', name: 'words', component: () => import('@/views/WordsView.vue'), meta: { label: '单词库', shortLabel: '词库', icon: 'Aa', nav: true, title: '单词库' } },
      { path: 'review', name: 'review', component: () => import('@/views/ReviewView.vue'), meta: { label: '在线复习', shortLabel: '复习', icon: '◫', nav: true, title: '在线复习' } },
      { path: 'daily/generate', name: 'daily-generate', component: () => import('@/views/DailyGenerateView.vue'), meta: { label: '复习表', shortLabel: '复习表', icon: '▤', nav: true, title: '复习表' } },
      { path: 'daily/sessions/:id', name: 'practice-session', component: () => import('@/views/PracticeSessionView.vue'), meta: { label: '复习回录', shortLabel: '回录', icon: '✓', title: '复习结果回录' } },
      { path: 'history', name: 'history', component: () => import('@/views/HistoryView.vue'), meta: { label: '复习历史', shortLabel: '历史', icon: '↺', nav: true, title: '复习历史' } },
      { path: ':pathMatch(.*)*', name: 'not-found', component: () => import('@/views/NotFoundView.vue'), meta: { label: '页面不存在', shortLabel: '404', icon: '?', title: '页面不存在' } },
    ],
  },
]

const router = createRouter({ history: createWebHistory(), routes, scrollBehavior: () => ({ top: 0 }) })
router.afterEach((to, from) => {
  document.title = `${String(to.meta.title || to.meta.label || '拾词')} · 单词记忆`
  if (from.matched.length) {
    nextTick(() => document.querySelector<HTMLElement>('#main-content')?.focus({ preventScroll: true }))
  }
})
export default router
