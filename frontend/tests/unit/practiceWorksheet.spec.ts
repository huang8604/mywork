import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import PracticeWorksheet from '@/components/PracticeWorksheet.vue'

const session: any = {
  session_id: 1,
  status: 'active',
  strategy_version: 'v1',
  seed: 1,
  strategy_params: { new_words_limit: 1, error_words_limit: 0, due_words_limit: 0, custom_words_limit: 0, fallback_unreviewed_days: 3, word_ids: [] },
  requested_counts: {},
  actual_counts: {},
  created_by_actor_type: 'web_user',
  created_by_actor_id: null,
  skill_name: null,
  skill_version: null,
  version: 1,
  generated_at: '2026-07-20T00:00:00Z',
  printed_at: null,
  completed_at: null,
  archived_at: null,
  title: null,
  note: null,
  items: [
    {
      item_id: 1, position: 1, word_id: 1,
      word: { en_word: 'camera', phonetic: 'ˈkæmərə', cn_meaning: '相机', example_sentence: 'I have a camera.' },
      source_categories: ['new'], reason: 'new', latest_review_log_id: null,
    },
  ],
}

describe('PracticeWorksheet', () => {
  it('shows the word and phonetic in separate columns', () => {
    const w = mount(PracticeWorksheet, { props: { session, answer: false, mode: 'en-to-cn' } })
    expect(w.get('.word-cell').text()).toBe('camera')
    expect(w.get('.phonetic-cell').text()).toBe('/ˈkæmərə/')
  })

  it('does NOT draw underlines for the blanked side (cn-to-en blanks English)', () => {
    const w = mount(PracticeWorksheet, { props: { session, answer: false, mode: 'cn-to-en' } })
    const cell = w.get('.word-cell')
    expect(cell.text().trim()).toBe('')
    expect(cell.text()).not.toContain('___')
  })

  it('blanks the Chinese side in en-to-cn recall (no underline)', () => {
    const w = mount(PracticeWorksheet, { props: { session, answer: false, mode: 'en-to-cn' } })
    const cnCell = w.get('.meaning-cell')
    expect(cnCell.text()).toBe('')
    expect(cnCell.text()).not.toContain('___')
  })

  it('shows the full example sentence (no fill-in-blank underscores)', () => {
    const w = mount(PracticeWorksheet, { props: { session, answer: false, mode: 'en-to-cn' } })
    const ex = w.get('.example-cell')
    expect(ex.text()).toContain('I have a camera.')
    expect(ex.text()).not.toContain('_____')
  })

  it('renders — when there is no example sentence', () => {
    const s: any = { ...session, items: [{ ...session.items[0], word: { ...session.items[0].word, example_sentence: null } }] }
    const w = mount(PracticeWorksheet, { props: { session: s, answer: false, mode: 'en-to-cn' } })
    expect(w.get('.example-cell').text()).toContain('—')
  })

  it('answer mode shows word, phonetic, chinese, and full example together', () => {
    const w = mount(PracticeWorksheet, { props: { session, answer: true, mode: 'cn-to-en' } })
    expect(w.get('.word-cell').text()).toContain('camera')
    expect(w.get('.phonetic-cell').text()).toContain('/ˈkæmərə/')
    expect(w.get('.meaning-cell').text()).toContain('相机')
    expect(w.get('.example-cell').text()).toContain('I have a camera.')
  })

  it('uses separate word and phonetic columns with matching colspan', () => {
    const w = mount(PracticeWorksheet, { props: { session, answer: false, mode: 'en-to-cn' } })
    const headerRow = w.findAll('thead tr')[1]
    expect(headerRow.findAll('th').map(h => h.text())).toEqual(['序号', '单词', '音标', '中文释义', '例句'])
    expect(w.findAll('thead tr')[0].find('th').attributes('colspan')).toBe('5')
  })

  it('applies the selected worksheet font size to screen and print content', () => {
    const w = mount(PracticeWorksheet, { props: { session, answer: false, mode: 'en-to-cn', fontSize: 'large' } })
    expect(w.get('.worksheet').attributes('style')).toContain('--worksheet-font-size: 12pt')
    expect(w.get('.worksheet').attributes('style')).toContain('--worksheet-word-font-size: 16pt')
  })

  it('labels the paper without exposing an internal session id', () => {
    const w = mount(PracticeWorksheet, { props: { session, answer: true, mode: 'cn-to-en' } })
    expect(w.text()).toContain('参考答案')
    expect(w.text()).toContain('看中文写英文')
    expect(w.text()).not.toContain('会话')
    expect(w.text()).not.toContain('#1')
  })
})
