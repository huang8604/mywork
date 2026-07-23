import { mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import SystemView from '@/views/SystemView.vue'
import { scopeLabel, scopesForDisplay } from '@/utils/apiScopes'
import { ALL_API_SCOPES } from '@/types/domain'

vi.mock('@/api/apiClients', () => ({
  listApiClients: vi.fn().mockResolvedValue([]),
  createApiClient: vi.fn(),
  deleteApiClient: vi.fn(),
  rotateApiToken: vi.fn(),
  updateApiClient: vi.fn(),
  disableApiClient: vi.fn(),
  revokeApiToken: vi.fn(),
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

  it('renders both section headings and the backup button (mount smoke)', async () => {
    const wrapper = mount(SystemView, { global: { stubs: ['el-table', 'el-table-column', 'el-dialog', 'el-checkbox-group', 'el-checkbox', 'el-tag', 'el-button'] } })
    // flush onMounted -> listApiClients
    await Promise.resolve()
    await Promise.resolve()
    const text = wrapper.text()
    expect(text).toContain('API 令牌')
    expect(text).toContain('数据备份')
    // The 「新增客户端」 and 「下载整库备份」 buttons render as el-button stubs
    expect(wrapper.findAll('el-button-stub').length).toBeGreaterThanOrEqual(2)
    // The page calls listApiClients() on mount (mocked); no crash.
    expect(wrapper.findComponent(SystemView).exists()).toBe(true)
  })
})
