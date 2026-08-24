<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { normalizeApiError } from '@/api/client'
import {
  createApiClient,
  deleteApiClient,
  disableApiClient,
  listApiClients,
  revokeApiToken,
  rotateApiToken,
  updateApiClient,
} from '@/api/apiClients'
import { apiClient } from '@/api/client'
import { getAudioSettings, getDictionaryAudioProgress, getIssueNote, pauseDictionaryAudio, resumeDictionaryAudio, saveAudioSettings, saveIssueNote, startDictionaryAudio } from '@/api/system'
import { scopeLabel } from '@/utils/apiScopes'
import { ALL_API_SCOPES } from '@/types/domain'
import type { ApiClient, ApiClientCreatePayload, ApiScope, AudioProvider, DictionaryAudioProgress, DictionaryAudioState, SystemAudioSettings, SystemIssueNote } from '@/types/domain'

const clients = ref<ApiClient[]>([])
const loading = ref(false)

// ---- Administrator issue / requirement notebook ----
const issueNote = ref<SystemIssueNote | null>(null)
const issueContent = ref('')
const issueLoading = ref(false)
const issueSaving = ref(false)
async function loadIssueNote() {
  issueLoading.value = true
  try {
    issueNote.value = await getIssueNote()
    issueContent.value = issueNote.value.content
  } catch (error) { ElMessage.error(normalizeApiError(error).message) }
  finally { issueLoading.value = false }
}
async function persistIssueNote() {
  if (!issueNote.value) return
  issueSaving.value = true
  try {
    issueNote.value = await saveIssueNote(issueContent.value, issueNote.value.version)
    issueContent.value = issueNote.value.content
    ElMessage.success('问题与需求记录已保存')
  } catch (error) {
    const normalized = normalizeApiError(error)
    if (normalized.isConflict) await loadIssueNote()
    ElMessage.error(normalized.isConflict ? '记录已被其他管理员修改，已加载最新内容' : normalized.message)
  } finally { issueSaving.value = false }
}

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

// ---- Local dictionary shared audio cache ----
const dictionaryAudio = ref<DictionaryAudioProgress | null>(null)
const dictionaryAudioBusy = ref(false)
const audioSettings = ref<SystemAudioSettings | null>(null)
const defaultAudioProvider = ref<AudioProvider>('mimo')
const dictionaryAudioProvider = ref<AudioProvider>('mimo')
const audioSettingsBusy = ref(false)
const autoImportDraft = ref(false)
const audioDraft = reactive<Record<AudioProvider, { base_url: string; api_key: string; model: string; voice: string }>>({
  mimo: { base_url: '', api_key: '', model: '', voice: '' },
  volc: { base_url: '', api_key: '', model: '', voice: '' },
})
// 清空数字/文本 = 清除覆盖，回落到环境变量默认值。
const volcTuningDraft = reactive<{ resource_id: string; speech_rate: number | null; loudness_rate: number | null; silence_ms: number | null }>({ resource_id: '', speech_rate: null, loudness_rate: null, silence_ms: null })
let dictionaryAudioTimer: number | null = null
const dictionaryAudioPercent = computed(() => dictionaryAudio.value?.total ? Math.round(dictionaryAudio.value.generated / dictionaryAudio.value.total * 100) : 0)
const dictionaryAudioStateLabels: Record<DictionaryAudioState, string> = {
  idle: '尚未启动', running: '后台生成中', paused: '已暂停', waiting_retry: '失败后等待重试',
  waiting_quota: '额度恢复等待中', completed: '已完成，定时扫描新增词',
}
function syncAudioDraft() {
  if (!audioSettings.value) return
  defaultAudioProvider.value = audioSettings.value.default_provider
  for (const provider of audioSettings.value.providers) {
    audioDraft[provider.id].base_url = provider.base_url
    audioDraft[provider.id].model = provider.model
    audioDraft[provider.id].voice = provider.voice
    audioDraft[provider.id].api_key = ''
  }
  autoImportDraft.value = audioSettings.value.auto_generate_on_import
  volcTuningDraft.resource_id = audioSettings.value.volc_tuning.resource_id
  volcTuningDraft.speech_rate = audioSettings.value.volc_tuning.speech_rate
  volcTuningDraft.loudness_rate = audioSettings.value.volc_tuning.loudness_rate
  volcTuningDraft.silence_ms = audioSettings.value.volc_tuning.silence_ms
}
async function loadAudioSettings() {
  try {
    audioSettings.value = await getAudioSettings()
    syncAudioDraft()
    dictionaryAudioProvider.value = audioSettings.value.default_provider
  } catch (error) { ElMessage.error(normalizeApiError(error).message) }
}
async function persistAudioSettings() {
  if (!audioSettings.value) return
  audioSettingsBusy.value = true
  try {
    audioSettings.value = await saveAudioSettings(
      defaultAudioProvider.value,
      audioSettings.value.version,
      { mimo: { ...audioDraft.mimo }, volc: { ...audioDraft.volc, ...volcTuningDraft } },
      autoImportDraft.value,
    )
    syncAudioDraft()
    ElMessage.success('音频模型与连接设置已保存')
  } catch (error) {
    const normalized = normalizeApiError(error)
    if (normalized.isConflict) await loadAudioSettings()
    ElMessage.error(normalized.isConflict ? '音频设置已变化，已加载最新设置' : normalized.message)
  } finally { audioSettingsBusy.value = false }
}
function audioModelLabel(provider: SystemAudioSettings['providers'][number]) {
  return `${provider.label} · ${provider.model} · ${provider.voice}${provider.enabled ? '' : '（未配置）'}`
}
function scheduleDictionaryAudioPoll() {
  if (dictionaryAudioTimer !== null) window.clearTimeout(dictionaryAudioTimer)
  const active = dictionaryAudio.value && ['running', 'waiting_retry', 'waiting_quota'].includes(dictionaryAudio.value.state)
  dictionaryAudioTimer = active ? window.setTimeout(loadDictionaryAudio, 1000) : null
}
async function loadDictionaryAudio() {
  try { dictionaryAudio.value = await getDictionaryAudioProgress() }
  catch (error) { ElMessage.error(normalizeApiError(error).message) }
  finally { scheduleDictionaryAudioPoll() }
}
async function runDictionaryAudioAction(action: 'start'|'pause'|'resume') {
  dictionaryAudioBusy.value = true
  try {
    dictionaryAudio.value = action === 'start' ? await startDictionaryAudio(dictionaryAudioProvider.value) : action === 'pause' ? await pauseDictionaryAudio() : await resumeDictionaryAudio()
    ElMessage.success(action === 'pause' ? '本地词库语音生成已暂停' : '本地词库语音生成已在后台运行')
  } catch (error) { ElMessage.error(normalizeApiError(error).message) }
  finally { dictionaryAudioBusy.value = false; scheduleDictionaryAudioPoll() }
}

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
onMounted(() => { void load(); void loadIssueNote(); void loadAudioSettings(); void loadDictionaryAudio() })
onBeforeUnmount(() => { if (dictionaryAudioTimer !== null) window.clearTimeout(dictionaryAudioTimer) })

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

async function removeClient(client: ApiClient) {
  try {
    await ElMessageBox.confirm(
      `确定永久删除客户端「${client.name}」？其全部 token 和授权范围会立即删除且无法恢复，相关审计记录仍会保留。`,
      '永久删除 API 客户端',
      { confirmButtonText: '永久删除', cancelButtonText: '取消', type: 'error' },
    )
    await deleteApiClient(client.id)
    ElMessage.success('API 客户端已永久删除')
    await load()
  } catch (error) {
    if (error === 'cancel' || error === 'close') return
    ElMessage.error(normalizeApiError(error).message)
  }
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

// ---- Restore ----
const restoreFile = ref<File | null>(null)
const restoring = ref(false)
const restoreResult = ref<{ backup_file: string; backup_bytes: number } | null>(null)
const restoreError = ref('')

function onRestoreFile(event: Event) {
  const files = (event.target as HTMLInputElement).files
  restoreFile.value = files?.[0] || null
  restoreResult.value = null
  restoreError.value = ''
}

async function doRestore() {
  const file = restoreFile.value
  if (!file) {
    restoreError.value = '请先选择一个 .db 备份文件'
    return
  }
  try {
    await ElMessageBox.confirm(
      '还原会用上传的备份覆盖当前全部数据(词库、复习历史、用户、令牌)。系统会先把当前数据自动备份为 pre-restore.db,可在还原后下载。建议另行下载一份整库备份再继续。',
      '确认还原整库',
      { confirmButtonText: '覆盖并还原', cancelButtonText: '取消', type: 'error' },
    )
  } catch {
    return
  }
  restoring.value = true
  restoreError.value = ''
  try {
    const form = new FormData()
    form.append('file', file)
    const res = await apiClient.post('/system/restore', form, { timeout: 120_000 })
    restoreResult.value = res.data.data
    ElMessage.success('已还原,即将刷新页面以加载新数据')
    setTimeout(() => location.reload(), 1200)
  } catch (error) {
    restoreError.value = normalizeApiError(error).message
  } finally {
    restoring.value = false
  }
}

async function downloadPreRestore() {
  try {
    const res = await apiClient.get('/system/pre-restore-backup', { responseType: 'blob' })
    const url = URL.createObjectURL(res.data)
    const a = document.createElement('a')
    a.href = url
    a.download = 'pre-restore.db'
    document.body.appendChild(a); a.click(); a.remove(); URL.revokeObjectURL(url)
  } catch (error) {
    ElMessage.error(normalizeApiError(error).message)
  }
}
</script>

<template>
  <section class="page">
    <div class="page-heading">
      <div>
        <p class="eyebrow">SYSTEM</p>
        <p>用户、复习历史、外部 Skill 接入与数据备份统一在这里管理。</p>
      </div>
    </div>

    <nav class="system-sections panel" aria-label="系统管理分类">
      <RouterLink to="/history"><span aria-hidden="true">↺</span><div><strong>复习历史</strong><small>查看流水并纠正复习结果</small></div></RouterLink>
      <RouterLink to="/users"><span aria-hidden="true">◐</span><div><strong>用户管理</strong><small>创建用户并维护访问角色</small></div></RouterLink>
      <a href="#dictionary-audio"><span aria-hidden="true">♫</span><div><strong>本地词库语音</strong><small>生成可复用的单词音频</small></div></a>
      <a href="#issue-notes"><span aria-hidden="true">✎</span><div><strong>问题与需求</strong><small>随时记录待修复事项</small></div></a>
      <a href="#api-clients"><span aria-hidden="true">⌁</span><div><strong>API 客户端</strong><small>管理外部 Skill 令牌</small></div></a>
      <a href="#backup"><span aria-hidden="true">↓</span><div><strong>数据备份</strong><small>下载可恢复的 SQLite 整库</small></div></a>
    </nav>

    <div id="dictionary-audio" class="panel">
      <div class="section-head">
        <div>
          <h2>本地词库语音导入</h2>
          <p class="muted">按本地词库逐词调用语音模型并保存为共享缓存。以后新增且命中本地词库的单词会直接复用，无需再次生成。</p>
        </div>
        <div class="button-row">
          <el-button data-testid="start-dictionary-audio" type="primary" :loading="dictionaryAudioBusy" :disabled="dictionaryAudio?.dictionary_available===false" @click="runDictionaryAudioAction('start')">扫描并生成缺失音频</el-button>
          <el-button v-if="dictionaryAudio&&dictionaryAudio.state!=='paused'&&dictionaryAudio.state!=='idle'" :loading="dictionaryAudioBusy" @click="runDictionaryAudioAction('pause')">暂停</el-button>
          <el-button v-if="dictionaryAudio?.state==='paused'" type="success" :loading="dictionaryAudioBusy" @click="runDictionaryAudioAction('resume')">恢复</el-button>
        </div>
      </div>
      <div v-if="audioSettings" class="audio-model-settings">
        <label class="audio-model-field">
          <span><strong>默认音频模型</strong><small>单词、批量、序号及词库任务未单独选择时使用</small></span>
          <span class="audio-model-control">
            <el-select v-model="defaultAudioProvider" aria-label="默认音频模型">
              <el-option v-for="provider in audioSettings.providers" :key="provider.id" :value="provider.id" :label="audioModelLabel(provider)" :disabled="!provider.enabled" />
            </el-select>
            <el-button data-testid="save-audio-settings" type="primary" :loading="audioSettingsBusy" @click="persistAudioSettings">保存设置</el-button>
          </span>
        </label>
        <label class="audio-model-field">
          <span><strong>导入单词时自动生成语音</strong><small>影响词库导入完成后是否自动排队生成发音</small></span>
          <span class="audio-model-control">
            <el-switch v-model="autoImportDraft" aria-label="导入单词时自动生成语音" />
          </span>
        </label>
        <div v-for="provider in audioSettings.providers" :key="provider.id" class="audio-provider-config">
          <div class="audio-provider-config-head">
            <strong>{{ provider.label }} 连接设置</strong>
            <small>{{ provider.api_key_configured ? `当前 Key：${provider.api_key_masked}` : '尚未配置 Key' }}</small>
          </div>
          <div class="audio-provider-fields">
            <el-input v-model="audioDraft[provider.id].base_url" :aria-label="`${provider.label}端点`" placeholder="端点 URL" />
            <el-input v-model="audioDraft[provider.id].api_key" :aria-label="`${provider.label}Key`" type="password" show-password placeholder="Key（留空保留现有 Key）" />
            <el-input v-model="audioDraft[provider.id].model" :aria-label="`${provider.label}模型`" placeholder="模型" />
            <el-input v-model="audioDraft[provider.id].voice" :aria-label="`${provider.label}音色`" placeholder="音色" />
          </div>
          <div v-if="provider.id === 'volc'" class="audio-provider-fields volc-tuning">
            <el-input v-model="volcTuningDraft.resource_id" aria-label="豆包资源 ID" placeholder="资源 ID（默认 seed-tts-2.0）" />
            <el-input-number v-model="volcTuningDraft.speech_rate" :min="-50" :max="100" aria-label="豆包语速" placeholder="语速" />
            <el-input-number v-model="volcTuningDraft.loudness_rate" :min="0" :max="100" aria-label="豆包音量" placeholder="音量" />
            <el-input-number v-model="volcTuningDraft.silence_ms" :min="0" :max="5000" :step="100" aria-label="豆包尾部停顿毫秒" placeholder="尾部停顿 ms" />
          </div>
          <p v-if="provider.id === 'volc'" class="muted audio-tuning-hint">语速 &lt;0 更平稳耐心；音量 &gt;0 更有力清晰；尾部停顿留白毫秒。清空数字 = 恢复环境变量默认值。</p>
        </div>
        <label class="audio-model-field">
          <span><strong>本次词库生成模型</strong><small>只影响下次“扫描并生成缺失音频”任务</small></span>
          <el-select v-model="dictionaryAudioProvider" aria-label="本次词库生成模型">
            <el-option v-for="provider in audioSettings.providers" :key="provider.id" :value="provider.id" :label="audioModelLabel(provider)" :disabled="!provider.enabled" />
          </el-select>
        </label>
        <p class="audio-model-catalog">
          <strong>支持模型：</strong>
          <span v-for="provider in audioSettings.providers" :key="provider.id">{{ audioModelLabel(provider) }}</span>
        </p>
      </div>
      <div v-if="dictionaryAudio" class="dictionary-audio-progress" aria-live="polite">
        <div class="dictionary-audio-summary"><strong>{{ dictionaryAudioStateLabels[dictionaryAudio.state] }}</strong><span>已生成 {{ dictionaryAudio.generated }} / {{ dictionaryAudio.total }}</span></div>
        <el-progress :percentage="dictionaryAudioPercent" :status="dictionaryAudio.state==='completed'?'success':undefined" />
        <div class="dictionary-audio-meta">
          <span>剩余 {{ dictionaryAudio.remaining }}</span><span v-if="dictionaryAudio.failed">本轮失败 {{ dictionaryAudio.failed }}</span><span v-if="dictionaryAudio.provider">模型 {{ dictionaryAudio.provider }}</span>
          <span v-if="dictionaryAudio.next_run_at">下次运行 {{ new Date(dictionaryAudio.next_run_at).toLocaleString('zh-CN') }}</span>
        </div>
        <p v-if="dictionaryAudio.state==='waiting_quota'" class="quota-note">已达到模型额度限制，系统将在 5 小时后自动继续；也可先暂停，额度恢复后手动恢复。</p>
        <p v-else-if="dictionaryAudio.last_error" class="error-box">{{ dictionaryAudio.last_error }}</p>
        <p v-if="!dictionaryAudio.dictionary_available" class="error-box">未找到本地词库文件，请检查 DICTIONARY_INDEX_PATH。</p>
      </div>
    </div>

    <div id="issue-notes" class="panel issue-notes" v-loading="issueLoading">
      <div class="section-head">
        <div>
          <h2>问题与需求记录</h2>
          <p class="muted">管理员可把待修复问题、复现步骤和新需求集中记录在这里，内容会随整库一起备份。</p>
        </div>
        <el-button type="primary" :loading="issueSaving" :disabled="!issueNote" @click="persistIssueNote">保存记录</el-button>
      </div>
      <el-input v-model="issueContent" type="textarea" :rows="12" maxlength="50000" show-word-limit placeholder="例如：&#10;【问题】……&#10;【复现步骤】……&#10;【需求】……" aria-label="问题与需求记录" />
      <div class="issue-note-meta">
        <span v-if="issueNote">最后保存：{{ new Date(issueNote.updated_at).toLocaleString('zh-CN') }}<template v-if="issueNote.updated_by"> · {{ issueNote.updated_by }}</template></span>
        <span v-if="issueNote && issueContent !== issueNote.content" class="unsaved">有未保存修改</span>
      </div>
    </div>

    <!-- Section A: API tokens -->
    <div id="api-clients" class="panel">
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
        <el-table-column label="操作" width="360">
          <template #default="{ row }">
            <el-button size="small" @click="rotate(row)">轮换 token</el-button>
            <el-button size="small" @click="openEditScopes(row)">改 scope</el-button>
            <el-button size="small" :type="row.status === 'disabled' ? 'success' : 'warning'" @click="disable(row)">
              {{ row.status === 'disabled' ? '启用' : '禁用' }}
            </el-button>
            <el-button size="small" type="danger" plain @click="removeClient(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
    </div>

    <!-- Section B: Backup -->
    <div id="backup" class="panel">
      <div class="section-head">
        <div>
          <h2>数据备份与还原</h2>
          <p class="muted">
            下载整库快照(词库 + 复习历史 + 会话);需要时用备份还原整库(还原前会自动再备份一份)。
          </p>
        </div>
        <div class="button-row">
          <el-button type="primary" :loading="backupLoading" @click="downloadBackup">下载整库备份(.db)</el-button>
        </div>
      </div>

      <el-divider />

      <div class="restore-block">
        <h3>还原整库</h3>
        <p class="muted">选择之前下载的 .db 备份,覆盖当前数据。还原前系统会先把当前库自动备份为 pre-restore.db。</p>
        <input class="file-input" type="file" accept=".db,application/octet-stream" @change="onRestoreFile" />
        <div class="button-row">
          <el-button type="danger" :loading="restoring" :disabled="!restoreFile" @click="doRestore">还原并覆盖</el-button>
          <el-button :disabled="!restoreResult" @click="downloadPreRestore">下载还原前自动备份</el-button>
        </div>
        <div v-if="restoreResult" class="restore-result" role="status">已自动备份 {{ restoreResult.backup_bytes }} 字节(pre-restore.db),整库还原成功。</div>
        <div v-if="restoreError" class="error-box" role="alert">{{ restoreError }}</div>
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
.system-sections { display: grid; grid-template-columns: repeat(5, minmax(0, 1fr)); gap: 10px; }
.system-sections a { min-height: 76px; display: flex; align-items: center; gap: 12px; padding: 12px; border: 1px solid var(--line); border-radius: 12px; color: var(--ink); text-decoration: none; background: #fff; }
.system-sections a:hover { border-color: var(--green-800); background: var(--green-100); }
.system-sections a > span { width: 34px; height: 34px; display: grid; place-items: center; border-radius: 10px; color: var(--green-800); background: var(--green-100); font-weight: 800; }
.system-sections a div { display: grid; gap: 3px; }.system-sections a small { color: var(--muted); }
.issue-notes { scroll-margin-top: 18px; }
.issue-note-meta { min-height: 22px; margin-top: 8px; display: flex; justify-content: space-between; gap: 12px; color: var(--muted); font-size: .78rem; }
.issue-note-meta .unsaved { color: #987226; font-weight: 700; }
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
.file-input { display: block; width: 100%; min-height: 48px; margin: 10px 0; }
.restore-block h3 { margin: 0 0 4px; }
.restore-result { margin-top: 10px; padding: 10px 12px; background: var(--green-100); border-radius: 8px; font-size: .88rem; color: #2f855a; }
.dictionary-audio-progress { display: grid; gap: 10px; padding: 14px; border: 1px solid var(--line); border-radius: 12px; background: #f7faf8; }
.audio-model-settings { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; margin-bottom: 14px; }
.audio-model-field { display: grid; gap: 8px; padding: 12px; border: 1px solid var(--line); border-radius: 10px; background: #fafcfb; }
.audio-model-field > span:first-child { display: grid; gap: 3px; }.audio-model-field small { color: var(--muted); }
.audio-model-control { display: grid; grid-template-columns: minmax(0, 1fr) auto; gap: 8px; }
.audio-provider-config { grid-column: 1 / -1; display: grid; gap: 10px; padding: 12px; border: 1px solid var(--line); border-radius: 10px; background: #fff; }
.audio-provider-config-head { display: flex; align-items: baseline; justify-content: space-between; gap: 10px; }.audio-provider-config-head small { color: var(--muted); }
.audio-provider-fields { display: grid; grid-template-columns: 1.3fr 1.3fr 1fr 1fr; gap: 8px; }
.audio-model-catalog { grid-column: 1 / -1; display: flex; gap: 8px 14px; flex-wrap: wrap; margin: 0; color: var(--muted); font-size: .82rem; }
.dictionary-audio-summary,.dictionary-audio-meta { display: flex; justify-content: space-between; gap: 12px; flex-wrap: wrap; }
.dictionary-audio-summary span,.dictionary-audio-meta { color: var(--muted); font-size: .85rem; }.dictionary-audio-meta { justify-content: flex-start; }
.quota-note { margin: 0; padding: 10px 12px; border-radius: 8px; background: #fff8e6; color: #76540e; }
@media (min-width: 480px) {
  .scope-grid { grid-template-columns: 1fr 1fr; }
}
@media (max-width: 900px) { .system-sections { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
@media (max-width: 700px) { .audio-model-settings { grid-template-columns: 1fr; } }
@media (max-width: 700px) { .audio-provider-fields { grid-template-columns: 1fr 1fr; } }
@media (max-width: 479px) { .system-sections { grid-template-columns: 1fr; }.audio-model-control { grid-template-columns: 1fr; }.audio-provider-fields { grid-template-columns: 1fr; }.audio-provider-config-head { display: grid; } }
</style>
