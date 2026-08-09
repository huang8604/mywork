import { mount } from '@vue/test-utils'
import { ref } from 'vue'
import { describe, expect, it, vi } from 'vitest'
import OnlineDictation from '@/views/review/OnlineDictation.vue'

vi.mock('@/composables/useDictationPlayer', () => ({
  useDictationPlayer: () => ({
    phase: ref('finished'), index: ref(1), total: ref(2), isSpeaking: ref(false), paused: ref(false),
    counts: ref({ played: 2, skipped: 0 }), voiceWarning: ref(null), supported: true,
    start: vi.fn(), replay: vi.fn(), skip: vi.fn(), nextAndPlay: vi.fn(), pause: vi.fn(), resume: vi.fn(), stop: vi.fn(),
  }),
}))

const session: any = {
  session_id: 8, title: '重点听写', items: [
    { item_id: 81, position: 1, word: { en_word: 'camera', cn_meaning: '相机' } },
    { item_id: 82, position: 2, word: { en_word: 'garden', cn_meaning: '花园' } },
  ],
}

describe('OnlineDictation', () => {
  it('shows every completed item below the summary as 已听写', () => {
    const wrapper = mount(OnlineDictation, {
      props: { session, sessions: [session] },
      global: { stubs: ['el-button', 'el-select', 'el-option', 'el-progress', 'el-input', 'el-slider', 'el-switch', 'el-radio-group', 'el-radio-button'] },
    })
    expect(wrapper.get('.dictation-results').text()).toContain('本轮听写结果')
    expect(wrapper.get('.dictation-results').text()).toContain('camera')
    expect(wrapper.get('.dictation-results').text()).toContain('garden')
    expect(wrapper.findAll('.dictation-results li')).toHaveLength(2)
    expect(wrapper.findAll('el-tag')).toHaveLength(2)
    expect(wrapper.findAll('el-tag').every(tag => tag.text() === '已听写')).toBe(true)
  })
})
