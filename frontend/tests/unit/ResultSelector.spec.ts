import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import ResultSelector from '@/components/ResultSelector.vue'

describe('ResultSelector', () => {
  it('offers all three textual results and emits the selected status', async () => {
    const wrapper = mount(ResultSelector, { props: { modelValue: null } })
    const buttons = wrapper.get('[role="group"]').findAll('button')
    expect(buttons.map((button) => button.text())).toEqual(expect.arrayContaining([expect.stringContaining('认识'), expect.stringContaining('不认识'), expect.stringContaining('跳过')]))
    await buttons[1].trigger('click')
    expect(wrapper.emitted('select')).toEqual([['unknown']])
    expect(wrapper.emitted('update:modelValue')).toEqual([['unknown']])
  })

  it('expresses current state without relying on color and blocks duplicate input', () => {
    const wrapper = mount(ResultSelector, { props: { modelValue: 'known', disabled: true } })
    const selected = wrapper.get('button[aria-pressed="true"]')
    expect(selected.text()).toContain('认识')
    expect(selected.attributes('disabled')).toBeDefined()
    expect(wrapper.findAll('button').every((button) => button.attributes('disabled') !== undefined)).toBe(true)
  })
})
