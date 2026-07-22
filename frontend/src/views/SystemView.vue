<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { normalizeApiError } from '@/api/client'
import {
  createApiClient,
  disableApiClient,
  listApiClients,
  revokeApiToken,
  rotateApiToken,
  updateApiClient,
} from '@/api/apiClients'
import { apiClient } from '@/api/client'
import { scopeLabel } from '@/utils/apiScopes'
import { ALL_API_SCOPES } from '@/types/domain'
import type { ApiClient, ApiClientCreatePayload, ApiScope } from '@/types/domain'

const clients = ref<ApiClient[]>([])
const loading = ref(false)

// ---- Create-dialog state ----
const createOpen = ref(false)
const submitting = ref(false)
const createForm = reactive({
  name: '',
  skill_name: '',
  skill_version: '',
  scopes: [] as ApiScope[],
  expires_days: 365,
  description: '',
})

// ---- Edit-scopes dialog ----
const scopesOpen = ref(false)
const scopesSubmitting = ref(false)
const scopesTarget = ref<ApiClient | null>(null)
const scopesDraft = reactive<{ scopes: ApiScope[] }>({ scopes: [] })

// ---- One-time plaintext token dialog ----
// Holds the plaintext token ONLY while the dialog is open. Cleared on close so
// it never persists in component state beyond the user's chance to copy it.
const tokenOpen = ref(false)
const tokenValue = ref('')
const tokenContext = ref('')

// ---- Backup ----
const backupLoading = ref(false)

async function load() {
  loading.value = true
  try {
    clients.value = await listApiClients()
  } catch (error) {
    ElMessage.error(normalizeApiError(error).message)
  } finally {
    loading.value = false
  }
}
onMounted(load)

function openCreate() {
  createForm.name = ''
  createForm.skill_name = ''
  createForm.skill_version = ''
  createForm.scopes = []
  createForm.expires_days = 365
  createForm.description = ''
  createOpen.value = true
}

const canSubmitCreate = computed(() =>
  createForm.name.trim().length > 0 &&
  createForm.skill_name.trim().length > 0 &&
  createForm.skill_version.trim().length > 0 &&
  createForm.scopes.length > 0 &&
  createForm.expires_days >= 1,
)

async function submitCreate() {
  submitting.value = true
  try {
    const payload: ApiClientCreatePayload = {
      name: createForm.name.trim(),
      skill_name: createForm.skill_name.trim(),
      skill_version: createForm.skill_version.trim(),
      scopes: [...createForm.scopes],
      expires_days: createForm.expires_days,
    }
    if (createForm.description.trim()) payload.description = createForm.description.trim()
    const created = await createApiClient(payload)
    createOpen.value = false
    showTokenOnce(created.token, `客户端「${created.name}」已创建`)
    await load()
  } catch (error) {
    ElMessage.error(normalizeApiError(error).message)
  } finally {
    submitting.value = false
  }
}

function showTokenOnce(token: string, context: string) {
  tokenValue.value = token
  tokenContext.value = context
  tokenOpen.value = true
}

function closeTokenDialog() {
  // Drop the plaintext from memory the moment the user closes the dialog.
  tokenValue.value = ''
  tokenContext.value = ''
  tokenOpen.value = false
}

async function copyToken() {
  try {
    await navigator.clipboard.writeText(tokenValue.value)
    ElMessage.success('已复制到剪贴板')
  } catch {
    ElMessage.error('复制失败,请手动选择文本复制')
  }
}

async function rotate(client: ApiClient) {
  try {
    await ElMessageBox.confirm(
      `确定轮换「${client.name}」的 token?现有 token 将立即失效。`,
      '确认轮换',
      { confirmButtonText: '轮换', cancelButtonText: '取消', type: 'warning' },
    )
    const result = await rotateApiToken(client.id)
    showTokenOnce(result.token, `「${client.name}」的新 token`)
    await load()
  } catch (error) {
    if (error === 'cancel' || error === 'close') return
    ElMessage.error(normalizeApiError(error).message)
  }
}

function openEditScopes(client: ApiClient) {
  scopesTarget.value = client
  scopesDraft.scopes = [...client.scopes] as ApiScope[]
  scopesOpen.value = true
}

async function submitScopes() {
  const target = scopesTarget.value
  if (!target) return
  if (scopesDraft.scopes.length === 0) {
    ElMessage.error('至少需要选择一个授权范围')
    return
  }
  scopesSubmitting.value = true
  try {
    await updateApiClient(target.id, { scopes: [...scopesDraft.scopes] })
    ElMessage.success('已更新授权范围')
    scopesOpen.value = false
    await load()
  } catch (error) {
    ElMessage.error(normalizeApiError(error).message)
  } finally {
    scopesSubmitting.value = false
  }
}

async function toggleStatus(client: ApiClient) {
  const disabling = client.status !== 'disabled'
  const verb = disabling ? '禁用' : '启用'
  try {
    await ElMessageBox.confirm(`确定${verb}客户端「${client.name}」?`, `确认${verb}`, {
      confirmButtonText: verb, cancelButtonText: '取消', type: disabling ? 'warning' : 'info',
    })
    // Disable uses the dedicated DELETE endpoint; re-enable goes via PATCH status.
    if (disabling) {
      await disableApiClient(client.id)
    } else {
      await updateApiClient(client.id, { status: 'active' })
    }
    ElMessage.success(`已${verb}`)
    await load()
  } catch (error) {
    if (error === 'cancel' || error === 'close') return
    ElMessage.error(normalizeApiError(error).message)
  }
}

async function disable(client: ApiClient) {
  // convenience alias kept for the table action label
  await toggleStatus(client)
}

async function revokeToken(client: ApiClient, tokenId: number) {
  try {
    await ElMessageBox.confirm('确定撤销该 token?此操作不可撤销。', '确认撤销', {
      confirmButtonText: '撤销', cancelButtonText: '取消', type: 'warning',
    })
    await revokeApiToken(client.id, tokenId)
    ElMessage.success('已撤销')
    await load()
  } catch (error) {
    if (error === 'cancel' || error === 'close') return
    ElMessage.error(normalizeApiError(error).message)
  }
}

async function downloadBackup() {
  backupLoading.value = true
  try {
    const res = await apiClient.get('/system/backup', { responseType: 'blob' })
    const url = URL.createObjectURL(res.data)
    const a = document.createElement('a')
    a.href = url
    a.download = 'vocab-backup.db'
    document.body.appendChild(a); a.click(); a.remove(); URL.revokeObjectURL(url)
  } catch (error) {
    ElMessage.error(normalizeApiError(error).message)
  } finally {
    backupLoading.value = false
  }
}
</script>

<template>
  <section class="page">
    <div class="page-heading">
      <div>
        <p class="eyebrow">SYSTEM</p>
        <p>管理员可在此管理外部 Skill 接入令牌,并下载整库备份。</p>
      </div>
    </div>

    <!-- Section A: API tokens -->
    <div class="panel">
      <div class="section-head">
        <div>
          <h2>API 令牌(外部 Skill 接入)</h2>
          <p class="muted">创建/轮换的 token 仅在弹出窗口中显示一次,请立即保存。</p>
        </div>
        <div class="button-row">
          <el-button type="primary" @click="openCreate">新增客户端</el-button>
        </div>
      </div>

      <el-table v-loading="loading" :data="clients" style="width: 100%">
        <el-table-column label="名称" min-width="160">
          <template #default="{ row }">
            <div class="cell-stack">
              <strong>{{ row.name }}</strong>
              <span v-if="row.description" class="muted small">{{ row.description }}</span>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="Skill" width="200">
          <template #default="{ row }">
            <span class="mono">{{ row.skill_name }}@{{ row.skill_version }}</span>
          </template>
        </el-table-column>
        <el-table-column label="授权范围" min-width="220">
          <template #default="{ row }">
            <div class="tag-list">
              <el-tag v-for="s in row.scopes" :key="s" size="small" type="info">{{ scopeLabel(s) }}</el-tag>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="100">
          <template #default="{ row }">
            <span :class="['badge', row.status === 'disabled' ? 'off' : 'on']">
              {{ row.status === 'disabled' ? '已禁用' : '正常' }}
            </span>
          </template>
        </el-table-column>
        <el-table-column label="Token" min-width="240">
          <template #default="{ row }">
            <div v-if="row.tokens.length === 0" class="muted small">无</div>
            <ul v-else class="token-list">
              <li v-for="t in row.tokens" :key="t.id">
                <span class="mono small">{{ t.prefix }}</span>
                <span :class="['token-state', `state-${t.state}`]">{{ t.state }}</span>
                <el-button
                  v-if="t.state !== 'revoked'"
                  size="small" link type="danger" @click="revokeToken(row, t.id)"
                >撤销</el-button>
              </li>
            </ul>
          </template>
        </el-table-column>
        <el-table-column prop="created_at" label="创建时间" width="220" />
        <el-table-column label="操作" width="280">
          <template #default="{ row }">
            <el-button size="small" @click="rotate(row)">轮换 token</el-button>
            <el-button size="small" @click="openEditScopes(row)">改 scope</el-button>
            <el-button size="small" :type="row.status === 'disabled' ? 'success' : 'warning'" @click="disable(row)">
              {{ row.status === 'disabled' ? '启用' : '禁用' }}
            </el-button>
          </template>
        </el-table-column>
      </el-table>
    </div>

    <!-- Section B: Backup -->
    <div class="panel">
      <div class="section-head">
        <div>
          <h2>数据备份</h2>
          <p class="muted">
            下载整库快照(词库 + 复习历史 + 会话)。还原:停容器 → 替换 <code>data/vocab.db</code> → 起容器。
          </p>
        </div>
        <div class="button-row">
          <el-button type="primary" :loading="backupLoading" @click="downloadBackup">下载整库备份(.db)</el-button>
        </div>
      </div>
    </div>

    <!-- Create dialog -->
    <el-dialog v-model="createOpen" title="新增客户端" width="min(520px, calc(100vw - 24px))">
      <label class="field">名称
        <input v-model="createForm.name" autocomplete="off" placeholder="例如:add-words skill" />
      </label>
      <label class="field">Skill 名称
        <input v-model="createForm.skill_name" autocomplete="off" placeholder="例如:add-words" />
      </label>
      <label class="field">Skill 版本
        <input v-model="createForm.skill_version" autocomplete="off" placeholder="例如:1.0.0" />
      </label>
      <label class="field">授权范围
        <el-checkbox-group v-model="createForm.scopes">
          <div class="scope-grid">
            <el-checkbox v-for="s in ALL_API_SCOPES" :key="s" :value="s" :label="s">
              <span class="mono small">{{ s }}</span>
              <span class="muted small"> · {{ scopeLabel(s) }}</span>
            </el-checkbox>
          </div>
        </el-checkbox-group>
      </label>
      <label class="field">有效期(天,默认 365)
        <input v-model.number="createForm.expires_days" type="number" min="1" max="3650" />
      </label>
      <label class="field">描述(可选)
        <input v-model="createForm.description" autocomplete="off" />
      </label>
      <template #footer>
        <el-button @click="createOpen = false">取消</el-button>
        <el-button type="primary" :loading="submitting" :disabled="!canSubmitCreate" @click="submitCreate">创建</el-button>
      </template>
    </el-dialog>

    <!-- Edit scopes dialog -->
    <el-dialog v-model="scopesOpen" :title="`修改授权范围 — ${scopesTarget?.name ?? ''}`" width="min(480px, calc(100vw - 24px))">
      <el-checkbox-group v-model="scopesDraft.scopes">
        <div class="scope-grid">
          <el-checkbox v-for="s in ALL_API_SCOPES" :key="s" :value="s" :label="s">
            <span class="mono small">{{ s }}</span>
            <span class="muted small"> · {{ scopeLabel(s) }}</span>
          </el-checkbox>
        </div>
      </el-checkbox-group>
      <template #footer>
        <el-button @click="scopesOpen = false">取消</el-button>
        <el-button type="primary" :loading="scopesSubmitting" @click="submitScopes">保存</el-button>
      </template>
    </el-dialog>

    <!-- One-time token dialog -->
    <el-dialog
      :model-value="tokenOpen"
      :title="tokenContext || 'Token 已生成'"
      width="min(560px, calc(100vw - 24px))"
      :close-on-click-modal="false"
      @close="closeTokenDialog"
    >
      <div class="token-warning">⚠ 请立即保存,关闭后将无法再次查看。</div>
      <div class="token-box">
        <code class="token-text">{{ tokenValue }}</code>
        <el-button size="small" type="primary" @click="copyToken">复制</el-button>
      </div>
      <template #footer>
        <el-button type="primary" @click="closeTokenDialog">我已保存</el-button>
      </template>
    </el-dialog>
  </section>
</template>

<style scoped>
.section-head { display: flex; align-items: flex-end; justify-content: space-between; gap: 16px; margin-bottom: 16px; flex-wrap: wrap; }
.section-head h2 { margin: 0 0 4px; }
.section-head .muted { margin: 0; }
.field { display: grid; gap: 6px; font-size: .85rem; color: var(--muted); margin-bottom: 14px; }
.field input { width: 100%; min-height: 40px; padding: 0 11px; border: 1px solid #dcdfe6; border-radius: 4px; background: #fff; color: var(--ink); }
.cell-stack { display: grid; gap: 2px; }
.muted { color: var(--muted); }
.small { font-size: .8rem; }
.mono { font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; }
.badge { padding: 2px 8px; border-radius: 10px; font-size: .78rem; }
.badge.on { background: var(--green-100); color: #2f855a; }
.badge.off { background: #fde2e2; color: #c0392b; }
.token-list { list-style: none; padding: 0; margin: 0; display: grid; gap: 4px; }
.token-list li { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.token-state { font-size: .72rem; padding: 1px 6px; border-radius: 8px; }
.token-state.state-active { background: var(--green-100); color: #2f855a; }
.token-state.state-expired { background: #fff7e6; color: #b07a00; }
.token-state.state-revoked { background: #fde2e2; color: #c0392b; }
.scope-grid { display: grid; grid-template-columns: 1fr; gap: 4px; }
.token-warning { color: #c0392b; font-weight: 600; margin-bottom: 10px; }
.token-box { display: flex; align-items: center; gap: 8px; background: #f5f7fa; border: 1px dashed #dcdfe6; border-radius: 6px; padding: 10px; }
.token-text { flex: 1; word-break: break-all; font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; font-size: .85rem; }
@media (min-width: 480px) {
  .scope-grid { grid-template-columns: 1fr 1fr; }
}
</style>
