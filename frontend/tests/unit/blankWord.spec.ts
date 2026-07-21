import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import PracticeWorksheet from '@/components/PracticeWorksheet.vue'
import { blankWord, escapeRegExp } from '@/utils/blankWord'
import type { PracticeSession } from '@/types/domain'

describe('blankWord', () => {
  it.each([
    ['Use a.b as a token, not axb.', 'a.b', 'Use _____ as a token, not axb.'],
    ['I write C++ daily.', 'C++', 'I write _____ daily.'],
    ['A mother-in-law arrived.', 'mother-in-law', 'A _____ arrived.'],
    ["I can't agree with cantaloupe.", "can't", 'I _____ agree with cantaloupe.'],
    ['Focus on FOCUS, not refocused.', 'focus', '_____ on _____, not refocused.'],
    ['CAFÉ noir and caféine.', 'café', '_____ noir and caféine.'],
  ])('safely blanks complete targets in %s', (sentence, word, expected) => {
    expect(blankWord(sentence, word)).toEqual({ text: expected, found: true })
  })

  it('reports empty and unmatched examples without changing them', () => {
    expect(blankWord('', 'word')).toEqual({ text: '', found: false })
    expect(blankWord('Nothing to replace.', 'word')).toEqual({ text: 'Nothing to replace.', found: false })
    expect(escapeRegExp('a.b[c]+')).toBe('a\\.b\\[c\\]\\+')
  })

  it('renders malicious-looking snapshots as text and keeps answer numbering aligned', () => {
    const session = {
      session_id: 7, status: 'active', strategy_version: 'v1', seed: 1, strategy_params: { new_words_limit: 1, error_words_limit: 0, due_words_limit: 0, custom_words_limit: 0, fallback_unreviewed_days: 3, word_ids: [] }, requested_counts: {}, actual_counts: {},
      created_by_actor_type: 'web_user', created_by_actor_id: null, skill_name: null, skill_version: null, version: 1,
      generated_at: '2026-07-20T00:00:00Z', printed_at: null, completed_at: null, archived_at: null,
      items: [{ item_id: 1, position: 1, word_id: 1, word: { en_word: '<img src=x onerror=alert(1)>', phonetic: null, cn_meaning: '<script>bad()</script>', example_sentence: 'safe text' }, source_categories: ['new'], reason: 'new', latest_review_log_id: null }], rounds: [],
    } as PracticeSession
    const question = mount(PracticeWorksheet, { props: { session, mode: 'cn-to-en' } })
    const answer = mount(PracticeWorksheet, { props: { session, mode: 'cn-to-en', answer: true } })
    expect(question.find('img').exists()).toBe(false); expect(answer.find('script').exists()).toBe(false)
    expect(answer.text()).toContain('<img src=x onerror=alert(1)>')
    expect(question.findAll('tbody .number-cell').map(node=>node.text())).toEqual(answer.findAll('tbody .number-cell').map(node=>node.text()))
  })
})
