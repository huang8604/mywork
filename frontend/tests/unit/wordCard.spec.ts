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
  audio_path: 'words/camera.mp3',
  cn_audio_ready: true,
  is_custom: false,
  tags: [],
  version: 1,
  stats: { total_attempts: 5, accuracy: .6, known_count: 3, unknown_count: 2, last_reviewed_at: '2026-07-20T08:00:00Z' },
}

describe('WordCard', () => {
  it('normalizes phonetic slashes instead of double-wrapping', () => {
    const wrapper = mount(WordCard, { props: { word } })
    expect(wrapper.text()).toContain('/ˈkæmərə/')
    expect(wrapper.text()).not.toContain('//ˈkæmərə//')
    expect(wrapper.text()).toContain('成功 3')
    expect(wrapper.text()).toContain('失败 2')
    expect(wrapper.text()).toContain('英文 已生成 · 中文 已生成')
    expect(wrapper.text()).toContain('播放英文')
    expect(wrapper.text()).toContain('播放中文')
    expect(wrapper.text()).toContain('重生成中英文')
    expect(wrapper.text()).toContain('上次背诵')
  })

  it('emits the selected audio language', async () => {
    const wrapper = mount(WordCard, { props: { word } })
    const buttons = wrapper.findAll('el-button')
    await buttons.find(button => button.text().includes('播放英文'))!.trigger('click')
    await buttons.find(button => button.text().includes('播放中文'))!.trigger('click')
    expect(wrapper.emitted('playAudio')).toEqual([['en'], ['zh']])
  })
})
