import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import SystemView from '@/views/SystemView.vue'
import { scopeLabel, scopesForDisplay } from '@/utils/apiScopes'
import { ALL_API_SCOPES } from '@/types/domain'
import { saveAudioSettings, startDictionaryAudio } from '@/api/system'

vi.mock('@/api/apiClients', () => ({
  listApiClients: vi.fn().mockResolvedValue([]),
  createApiClient: vi.fn(),
  deleteApiClient: vi.fn(),
  rotateApiToken: vi.fn(),
  updateApiClient: vi.fn(),
  disableApiClient: vi.fn(),
  revokeApiToken: vi.fn(),
}))

vi.mock('@/api/system', () => ({
  getIssueNote: vi.fn().mockResolvedValue({
    content: '待修复：打印标题', version: 2, updated_at: '2026-08-10T00:00:00Z', updated_by: 'admin',
  }),
  saveIssueNote: vi.fn(),
  getAudioSettings: vi.fn().mockResolvedValue({
    default: 'volc', current: 'volc', default_provider: 'volc', version: 2,
    updated_at: '2026-08-10T00:00:00Z', updated_by: 'admin',
    providers: [
      { id: 'mimo', label: 'mimo', enabled: true, base_url: 'https://mimo.example/v1', api_key_configured: true, api_key_masked: 'mi****mo', model: 'mimo-v2.5-tts', voice: 'Chloe' },
      { id: 'volc', label: '豆包 seed-tts-2.0', enabled: true, base_url: 'https://volc.example', api_key_configured: true, api_key_masked: 'vo****lc', model: 'doubao-seed-tts-2.0', voice: 'Tina' },
    ],
  }),
  saveAudioSettings: vi.fn().mockResolvedValue({
    default: 'volc', current: 'volc', default_provider: 'volc', version: 3,
    updated_at: '2026-08-10T01:00:00Z', updated_by: 'admin',
    providers: [
      { id: 'mimo', label: 'mimo', enabled: true, base_url: 'https://mimo.example/v1', api_key_configured: true, api_key_masked: 'mi****mo', model: 'mimo-v2.5-tts', voice: 'Chloe' },
      { id: 'volc', label: '豆包 seed-tts-2.0', enabled: true, base_url: 'https://volc.example', api_key_configured: true, api_key_masked: 'vo****lc', model: 'doubao-seed-tts-2.0', voice: 'Tina' },
    ],
  }),
  getDictionaryAudioProgress: vi.fn().mockResolvedValue({
    state: 'paused', total: 100, generated: 25, failed: 2, remaining: 75,
    provider: 'mimo', next_run_at: null, last_error: null, updated_at: null,
    dictionary_available: true,
  }),
  startDictionaryAudio: vi.fn().mockResolvedValue({
    state: 'running', total: 100, generated: 25, failed: 0, remaining: 75,
    provider: 'volc', next_run_at: null, last_error: null, updated_at: null,
    dictionary_available: true,
  }),
  pauseDictionaryAudio: vi.fn(),
  resumeDictionaryAudio: vi.fn(),
}))

// client is only used directly for the backup download; stub its network call.
vi.mock('@/api/client', async () => {
  const actual = await vi.importActual<typeof import('@/api/client')>('@/api/client')
  return {
    ...actual,
    apiClient: { get: vi.fn(() => Promise.resolve({ data: new Blob() })) },
  }
})

describe('apiScopes helpers', () => {
  it('labels all canonical ALL_API_SCOPES without falling back to the raw string', () => {
    for (const scope of ALL_API_SCOPES) {
      expect(scopeLabel(scope)).not.toBe(scope)
    }
  })

  it('falls back to the raw string for unknown scopes', () => {
    expect(scopeLabel('users:manage')).toBe('users:manage')
  })

  it('keeps only known scopes, dropping anything else', () => {
    const mixed = ['words:read', 'bogus:scope', 'reviews:write', '']
    expect(scopesForDisplay(mixed)).toEqual(['words:read', 'reviews:write'])
  })
})

describe('SystemView', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('renders notebook and supported audio models, then starts with the selected model', async () => {
    const wrapper = mount(SystemView, { global: { stubs: ['el-table', 'el-table-column', 'el-dialog', 'el-checkbox-group', 'el-checkbox', 'el-tag', 'el-button', 'el-input', 'el-select', 'el-option', 'el-progress'] } })
    // flush onMounted -> listApiClients
    await flushPromises()
    const text = wrapper.text()
    expect(text).toContain('API 令牌')
    expect(text).toContain('数据备份')
    expect(text).toContain('本地词库语音导入')
    expect(text).toContain('问题与需求记录')
    expect(text).toContain('默认音频模型')
    expect(text).toContain('本次词库生成模型')
    expect(text).toContain('已生成 25 / 100')
    expect(text).toContain('mimo · mimo-v2.5-tts · Chloe')
    expect(text).toContain('豆包 seed-tts-2.0 · doubao-seed-tts-2.0 · Tina')
    // The 「新增客户端」 and 「下载整库备份」 buttons render as el-button stubs
    expect(wrapper.findAll('el-button-stub').length).toBeGreaterThanOrEqual(2)
    // The page calls listApiClients() on mount (mocked); no crash.
    expect(wrapper.findComponent(SystemView).exists()).toBe(true)

    const start = wrapper.find('[data-testid="start-dictionary-audio"]')
    expect(start.exists()).toBe(true)
    await start.trigger('click')
    await flushPromises()
    expect(startDictionaryAudio).toHaveBeenCalledWith('volc')

    const saveDefault = wrapper.find('[data-testid="save-audio-settings"]')
    await saveDefault.trigger('click')
    await flushPromises()
    expect(saveAudioSettings).toHaveBeenCalledWith('volc', 2, expect.objectContaining({ mimo: expect.any(Object), volc: expect.any(Object) }))
  })
})
