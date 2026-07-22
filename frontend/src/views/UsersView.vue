<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { normalizeApiError } from '@/api/client'
import { createUser, deleteUser, listUsers, resetUserPassword, updateUser } from '@/api/users'
import type { WebRole, WebUser } from '@/types/domain'

const users = ref<WebUser[]>([])
const loading = ref(false)
const createOpen = ref(false)
const submitting = ref(false)
const form = reactive<{ username: string; password: string; role: WebRole }>({
  username: '',
  password: '',
  role: 'student',
})

async function load() {
  loading.value = true
  try {
    users.value = await listUsers()
  } catch (error) {
    ElMessage.error(normalizeApiError(error).message)
  } finally {
    loading.value = false
  }
}
onMounted(load)

function openCreate() {
  form.username = ''
  form.password = ''
  form.role = 'student'
  createOpen.value = true
}

async function submitCreate() {
  submitting.value = true
  try {
    await createUser({ ...form })
    ElMessage.success('已创建用户')
    createOpen.value = false
    await load()
  } catch (error) {
    ElMessage.error(normalizeApiError(error).message)
  } finally {
    submitting.value = false
  }
}

async function toggleDisabled(user: WebUser) {
  const next = !user.disabled_at
  try {
    await updateUser(user.id, { disabled: next })
    ElMessage.success(next ? '已禁用' : '已启用')
    await load()
  } catch (error) {
    ElMessage.error(normalizeApiError(error).message)
  }
}

async function resetPwd(user: WebUser) {
  try {
    const result = await ElMessageBox.prompt('请输入新密码（至少 6 位）', `重置「${user.username}」的密码`, {
      confirmButtonText: '保存',
      cancelButtonText: '取消',
      inputType: 'password',
      inputValidator: (value: string) => value.length >= 6,
      inputErrorMessage: '密码至少 6 位',
    })
    await resetUserPassword(user.id, result.value)
    ElMessage.success('密码已重置')
  } catch (error) {
    if (error === 'cancel' || error === 'close') return
    ElMessage.error(normalizeApiError(error).message)
  }
}

async function remove(user: WebUser) {
  try {
    await ElMessageBox.confirm(`确定删除用户「${user.username}」？`, '确认删除', {
      confirmButtonText: '删除',
      cancelButtonText: '取消',
      type: 'warning',
    })
    await deleteUser(user.id)
    ElMessage.success('已删除')
    await load()
  } catch (error) {
    if (error === 'cancel' || error === 'close') return
    ElMessage.error(normalizeApiError(error).message)
  }
}
</script>

<template>
  <section class="page">
    <div class="page-heading">
      <div><p class="eyebrow">USERS</p><p>管理员拥有全部权限；学生仅可使用「在线复习」。</p></div>
      <div class="button-row"><el-button type="primary" @click="openCreate">新增用户</el-button></div>
    </div>
    <div class="panel">
      <el-table v-loading="loading" :data="users" style="width: 100%">
        <el-table-column prop="username" label="用户名" />
        <el-table-column label="角色" width="140">
          <template #default="{ row }">
            <el-tag :type="row.role === 'admin' ? 'primary' : 'info'" size="small">
              {{ row.role === 'admin' ? '管理员' : '学生' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="100">
          <template #default="{ row }">
            <span :class="['badge', row.disabled_at ? 'off' : 'on']">{{ row.disabled_at ? '已禁用' : '正常' }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="created_at" label="创建时间" width="220" />
        <el-table-column label="操作" width="280">
          <template #default="{ row }">
            <el-button size="small" @click="resetPwd(row)">改密</el-button>
            <el-button size="small" @click="toggleDisabled(row)">{{ row.disabled_at ? '启用' : '禁用' }}</el-button>
            <el-button size="small" type="danger" @click="remove(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
    </div>

    <el-dialog v-model="createOpen" title="新增用户" width="min(420px, calc(100vw - 24px))">
      <label class="field">用户名<input v-model="form.username" autocomplete="off" /></label>
      <label class="field">密码（至少 6 位）<input v-model="form.password" type="password" autocomplete="new-password" /></label>
      <label class="field">角色
        <el-select v-model="form.role">
          <el-option label="管理员（全部权限）" value="admin" />
          <el-option label="学生（仅在线复习）" value="student" />
        </el-select>
      </label>
      <template #footer>
        <el-button @click="createOpen = false">取消</el-button>
        <el-button type="primary" :loading="submitting" :disabled="!form.username.trim() || form.password.length < 6" @click="submitCreate">创建</el-button>
      </template>
    </el-dialog>
  </section>
</template>

<style scoped>
.field { display: grid; gap: 6px; font-size: .85rem; color: var(--muted); margin-bottom: 14px; }
.field input { width: 100%; min-height: 40px; padding: 0 11px; border: 1px solid #dcdfe6; border-radius: 4px; background: #fff; color: var(--ink); }
.badge { padding: 2px 8px; border-radius: 10px; font-size: .78rem; }
.badge.on { background: var(--green-100); color: #2f855a; }
.badge.off { background: #fde2e2; color: #c0392b; }
</style>
