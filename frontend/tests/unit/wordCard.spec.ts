import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import WordCard from '@/components/WordCard.vue'

const word: any = {
  id: 1,
  en_word: 'camera',
  normalized_en_word: 'camera',
  phonetic: '/ˈkæmərə/',
  cn_meaning: '相机',
  example_sentence: null,
  is_custom: false,
  tags: [],
  version: 1,
  stats: { total_attempts: 0, accuracy: null },
}

describe('WordCard', () => {
  it('normalizes phonetic slashes instead of double-wrapping', () => {
    const wrapper = mount(WordCard, { props: { word } })
    expect(wrapper.text()).toContain('/ˈkæmərə/')
    expect(wrapper.text()).not.toContain('//ˈkæmərə//')
  })
})
