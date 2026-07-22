<script setup lang="ts">
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { routes, type NavMeta } from '@/router'
import { usePreferencesStore } from '@/stores/preferences'
import { useAuthStore } from '@/stores/auth'

const route = useRoute(); const router = useRouter(); const preferences = usePreferencesStore(); const auth = useAuthStore()
const children = routes.find((item) => item.path === '/' && item.children)?.children ?? []
const navItems = computed(() => children.flatMap((item) => {
  const meta = item.meta as unknown as NavMeta | undefined
  if (!meta?.nav) return []
  if (meta.roles && (!auth.role || !meta.roles.includes(auth.role))) return []
  return [{ name: item.name, ...meta }]
}))
function focusMain() { document.querySelector<HTMLElement>('#main-content')?.focus({ preventScroll: true }) }
async function logout() { await auth.logout(); router.push('/login') }
</script>

<template>
  <a class="skip-link" href="#main-content" @click.prevent="focusMain">跳到主要内容</a>
  <div class="app-shell" :class="{ 'sidebar-collapsed': preferences.sidebarCollapsed }">
    <aside class="sidebar" aria-label="主导航">
      <div class="brand"><span class="brand-mark">拾</span><div class="brand-copy"><strong>拾词</strong><small>Word Memory</small></div></div>
      <nav class="side-nav">
        <RouterLink v-for="item in navItems" :key="item.name as string" :to="{ name: item.name }" class="nav-item">
          <span class="nav-icon" aria-hidden="true">{{ item.icon }}</span>
          <span class="nav-label">{{ item.label }}</span>
        </RouterLink>
      </nav>
      <button class="collapse-button" type="button" :aria-label="preferences.sidebarCollapsed ? '展开侧栏' : '收起侧栏'" @click="preferences.toggleSidebar">
        {{ preferences.sidebarCollapsed ? '›' : '‹' }}<span class="nav-label">收起侧栏</span>
      </button>
    </aside>

    <div class="content-shell">
      <header class="topbar"><div><p class="eyebrow">WORD MEMORY</p><h1>{{ route.meta.title || route.meta.label }}</h1></div><div class="topbar-right"><span v-if="auth.username" class="who">{{ auth.username }}</span><el-button size="small" @click="logout">退出</el-button></div></header>
      <main id="main-content" tabindex="-1"><RouterView /></main>
    </div>

    <nav class="bottom-nav" aria-label="移动端主导航">
      <RouterLink v-for="item in navItems" :key="item.name as string" :to="{ name: item.name }" class="bottom-nav-item">
        <span aria-hidden="true">{{ item.icon }}</span><small>{{ item.shortLabel }}</small>
      </RouterLink>
    </nav>
  </div>
</template>
