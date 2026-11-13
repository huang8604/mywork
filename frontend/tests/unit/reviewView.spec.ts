import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import ReviewView from '@/views/ReviewView.vue'
import ResultSelector from '@/components/ResultSelector.vue'
import { createRound, getSession, listSessions, putRoundResult } from '@/api/practiceSessions'
import type { PracticeSession } from '@/types/domain'

vi.mock('@/api/practiceSessions', () => ({
  listSessions: vi.fn(), getSession: vi.fn(), createRound: vi.fn(), putRoundResult: vi.fn(),
}))
vi.mock('@/api/reviews', () => ({ getTodayOnlineReviews: vi.fn().mockResolvedValue(null) }))
vi.mock('@/stores/auth', () => ({ useAuthStore: () => ({ role: 'student' }) }))

function worksheet(completedAt: string | null = null): PracticeSession {
  return {
    session_id: 1, title: '再次复习测试', status: completedAt ? 'completed' : 'active',
    generated_at: new Date().toISOString(), completed_at: completedAt,
    items: [{ item_id: 11, word: { en_word: 'warm', cn_meaning: '温暖' }, source_categories: [] }],
  } as unknown as PracticeSession
}

function render() {
  return mount(ReviewView, { global: { stubs: {
    'el-button': { template: '<button><slot /></button>' }, 'el-progress': true, 'el-skeleton': true,
    OnlineDictation: { props: ['sessions'], template: '<div class="dictation-sessions">{{ sessions.map(s => s.title).join() }}</div>' },
  } } })
}

describe('online review completed worksheets', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.useFakeTimers({ toFake: ['Date', 'setInterval', 'clearInterval'] })
    vi.setSystemTime(new Date('2026-11-13T10:00:00Z'))
    vi.mocked(listSessions).mockResolvedValue({ data: [worksheet()], meta: {} })
  })
  afterEach(() => vi.useRealTimers())

  it('keeps the completed worksheet after finishing and creates a new round on retry', async () => {
    vi.mocked(getSession).mockResolvedValueOnce(worksheet())
      .mockResolvedValue(worksheet(new Date().toISOString()))
    vi.mocked(createRound).mockResolvedValue({ round_id: 7 } as Awaited<ReturnType<typeof createRound>>)
    vi.mocked(putRoundResult).mockResolvedValue({ status: 'known' } as Awaited<ReturnType<typeof putRoundResult>>)
    const wrapper = render()
    await flushPromises()
    expect(listSessions).toHaveBeenCalledWith(1, 100, expect.any(AbortSignal), undefined, true)
    await wrapper.findAll('button').find(b => b.text() === '开始在线复习')!.trigger('click')
    await flushPromises()
    wrapper.findComponent(ResultSelector).vm.$emit('select', 'known')
    await flushPromises()
    await wrapper.get('.finish-summary button').trigger('click')
    expect(wrapper.get('.session-choice').text()).toContain('已完成 · 可再次复习')
    expect(wrapper.get('.review-intro').text()).toContain('再次复习')
    await wrapper.findAll('button').find(b => b.text() === '再次复习')!.trigger('click')
    await flushPromises()
    expect(createRound).toHaveBeenCalledTimes(2)
    expect(wrapper.find('.finish-summary').exists()).toBe(false)
    expect(wrapper.findComponent(ResultSelector).exists()).toBe(true)
    wrapper.unmount()
  })

  it('offers recent completed worksheets in dictation and hides them at 24 hours without reload', async () => {
    vi.mocked(getSession).mockResolvedValue(worksheet('2026-11-12T10:00:01Z'))
    const wrapper = render()
    await flushPromises()
    await wrapper.get('input[value="dictation"]').setValue(true)
    expect(wrapper.get('.dictation-sessions').text()).toContain('再次复习测试')
    await vi.advanceTimersByTimeAsync(1000)
    expect(wrapper.find('.dictation-sessions').exists()).toBe(false)
    expect(wrapper.text()).toContain('暂无可复习的复习表')
    wrapper.unmount()
  })
})
