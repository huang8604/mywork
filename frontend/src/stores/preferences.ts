import { defineStore } from 'pinia'
import { ref } from 'vue'

export const usePreferencesStore = defineStore('preferences', () => {
  const sidebarCollapsed = ref(false)
  const lastSessionId = ref<number | null>(null)
  function toggleSidebar() { sidebarCollapsed.value = !sidebarCollapsed.value }
  return { sidebarCollapsed, lastSessionId, toggleSidebar }
})
