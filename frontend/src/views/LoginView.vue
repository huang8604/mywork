<script setup lang="ts">
import { ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { useAuthStore } from '@/stores/auth'
import { normalizeApiError } from '@/api/client'
import type { WebRole } from '@/types/domain'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()

const username = ref('')
const password = ref('')
const loading = ref(false)

function defaultPath(role: WebRole | null) {
  return role === 'student' ? '/review' : '/dashboard'
}

async function submit() {
  if (!username.value.trim() || !password.value) {
    ElMessage.warning('请输入用户名和密码')
    return
  }
  loading.value = true
  try {
    const me = await auth.login(username.value.trim(), password.value)
    ElMessage.success('登录成功')
    const redirect = typeof route.query.redirect === 'string' ? route.query.redirect : null
    router.replace(redirect || defaultPath(me.role))
  } catch (error) {
    ElMessage.error(normalizeApiError(error).message)
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <section class="login-page">
    <form class="login-card panel" @submit.prevent="submit">
      <div class="brand"><span class="brand-mark">拾</span><div class="brand-copy"><strong>拾词</strong><small>Word Memory</small></div></div>
      <h1>登录</h1>
      <label class="field">用户名
        <input v-model="username" autocomplete="username" :disabled="loading" />
      </label>
      <label class="field">密码
        <input v-model="password" type="password" autocomplete="current-password" :disabled="loading" />
      </label>
      <el-button type="primary" :loading="loading" native-type="submit">登录</el-button>
    </form>
  </section>
</template>

<style scoped>
.login-page { min-height: 100vh; display: grid; place-items: center; padding: 24px; background: var(--app-bg, #f5f6f8); }
.login-card { width: min(380px, 100%); display: grid; gap: 14px; padding: 28px; }
.login-card .brand { display: flex; align-items: center; gap: 10px; }
.login-card .brand-mark { width: 32px; height: 32px; display: grid; place-items: center; border-radius: 8px; background: #409eff; color: #fff; font-weight: 800; }
.login-card .brand-copy { display: grid; line-height: 1.1; }
.login-card .brand-copy small { color: var(--muted); font-size: .72rem; }
.login-card h1 { margin: 0; font-size: 1.25rem; }
.field { display: grid; gap: 6px; font-size: .85rem; color: var(--muted); }
.field input { width: 100%; min-height: 42px; padding: 0 12px; border: 1px solid #dcdfe6; border-radius: 6px; background: #fff; color: var(--ink); }
.field input:focus { outline: none; border-color: #409eff; }
</style>
