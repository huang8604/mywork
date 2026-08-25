import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import SystemView from '@/views/SystemView.vue'
import { scopeLabel, scopesForDisplay } from '@/utils/apiScopes'
import { ALL_API_SCOPES } from '@/types/domain'
import { saveAudioSettings, startDictionaryAudio } from '@/api/system'

const providerInfo = vi.hoisted(() => [
  {
    id: 'volc', label: '豆包', enabled: true,
    api_url: 'https://openspeech.bytedance.com',
    base_url: 'https://openspeech.bytedance.com',
    api_key_configured: true, api_key_masked: 'ar****96',
    model: 'doubao-seed-tts-2.0', voice: 'zh_female_yingyujiaoxue_uranus_bigtts',
  },
  {
    id: 'mimo', label: 'Mimo', enabled: true,
    api_url: 'https://api.xiaomimimo.com/v1', base_url: 'https://api.xiaomimimo.com/v1',
    api_key_configured: true, api_key_masked: 'mi****ey',
    model: 'mimo-v2.5-tts', voice: 'Chloe',
  },
])

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
    default_provider: 'volc', providers: providerInfo,
    api_url: providerInfo[0].api_url, api_key_configured: true, api_key_masked: 'ar****96',
    model: 'doubao-seed-tts-2.0', voice: providerInfo[0].voice, configured: true, version: 2,
    auto_generate_on_import: false,
    updated_at: '2026-08-10T00:00:00Z', updated_by: 'admin',
  }),
  saveAudioSettings: vi.fn().mockResolvedValue({
    default_provider: 'volc', providers: providerInfo,
    api_url: providerInfo[0].api_url, api_key_configured: true, api_key_masked: 'ar****96',
    model: 'doubao-seed-tts-2.0', voice: providerInfo[0].voice, configured: true, version: 3,
    auto_generate_on_import: false,
    updated_at: '2026-08-10T01:00:00Z', updated_by: 'admin',
  }),
  testAudioSettings: vi.fn().mockResolvedValue({
    blob: new Blob(['audio']), provider: 'volc', model: 'doubao-seed-tts-2.0',
    voice: 'zh_female_yingyujiaoxue_uranus_bigtts',
  }),
  getDictionaryAudioProgress: vi.fn().mockResolvedValue({
    state: 'paused', total: 100, generated: 25, failed: 2, remaining: 75,
    provider: 'volc', model: 'doubao-seed-tts-2.0', voice: providerInfo[0].voice,
    last_provider: 'mimo', last_model: 'mimo-v2.5-tts', last_voice: 'Chloe',
    next_run_at: null, last_error: null, updated_at: null,
    dictionary_available: true,
  }),
  startDictionaryAudio: vi.fn().mockResolvedValue({
    state: 'running', total: 100, generated: 25, failed: 0, remaining: 75,
    provider: 'volc', model: 'doubao-seed-tts-2.0', voice: providerInfo[0].voice,
    last_provider: 'volc', last_model: 'doubao-seed-tts-2.0', last_voice: providerInfo[0].voice,
    next_run_at: null, last_error: null, updated_at: null,
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

  it('renders the two provider slots, then starts with Doubao by default', async () => {
    const wrapper = mount(SystemView, { global: { stubs: ['el-table', 'el-table-column', 'el-dialog', 'el-checkbox-group', 'el-checkbox', 'el-tag', 'el-button', 'el-input', 'el-select', 'el-option', 'el-progress'] } })
    // flush onMounted -> listApiClients
    await flushPromises()
    const text = wrapper.text()
    expect(text).toContain('API 令牌')
    expect(text).toContain('数据备份')
    expect(text).toContain('本地词库语音导入')
    expect(text).toContain('问题与需求记录')
    expect(text).toContain('豆包 API URL')
    expect(text).toContain('豆包 API Key')
    expect(text).toContain('Mimo')
    expect(text).toContain('导入单词时自动生成语音')
    expect(text).not.toContain('默认音频模型')
    expect(text).toContain('doubao-seed-tts-2.0')
    expect(text).toContain('已生成 25 / 100')
    expect(text).toContain('Mimo · mimo-v2.5-tts')
    // The 「新增客户端」 and 「下载整库备份」 buttons render as el-button stubs
    expect(wrapper.findAll('el-button-stub').length).toBeGreaterThanOrEqual(2)
    // The page calls listApiClients() on mount (mocked); no crash.
    expect(wrapper.findComponent(SystemView).exists()).toBe(true)

    const start = wrapper.find('[data-testid="start-dictionary-audio"]')
    expect(start.exists()).toBe(true)
    expect(wrapper.find('[data-testid="test-audio-settings"]').exists()).toBe(true)
    await start.trigger('click')
    await flushPromises()
    expect(startDictionaryAudio).toHaveBeenCalledWith('volc')

    const saveDefault = wrapper.find('[data-testid="save-audio-settings"]')
    await saveDefault.trigger('click')
    await flushPromises()
    expect(saveAudioSettings).toHaveBeenCalledWith(
      'volc',
      {
        mimo: { base_url: 'https://api.xiaomimimo.com/v1', api_key: '' },
        volc: { base_url: 'https://openspeech.bytedance.com', api_key: '' },
      },
      2,
      false,
    )
  })
})
