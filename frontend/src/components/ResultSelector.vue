<script setup lang="ts">
import type { ReviewStatus } from '@/types/domain'
const props = withDefaults(defineProps<{ modelValue: ReviewStatus | null; disabled?: boolean; compact?: boolean }>(), { disabled: false, compact: false })
const emit = defineEmits<{ 'update:modelValue': [value: ReviewStatus | null]; select: [value: ReviewStatus | null] }>()
const options: Array<{ value: ReviewStatus; label: string; icon: string; key: string }> = [
  { value: 'known', label: '认识', icon: '✓', key: '1' }, { value: 'unknown', label: '不认识', icon: '×', key: '2' }, { value: 'skipped', label: '跳过', icon: '→', key: '3' },
]
function toggle(value: ReviewStatus) {
  const next = props.modelValue === value ? null : value
  emit('update:modelValue', next)
  emit('select', next)
}
</script>
<template>
  <div class="result-selector" :class="{ compact }" role="group" aria-label="选择复习结果">
    <button v-for="item in options" :key="item.value" type="button" class="result-button" :class="[item.value,{selected:modelValue===item.value}]" :disabled="disabled" :aria-pressed="modelValue===item.value" @click="toggle(item.value)">
      <span class="result-icon" aria-hidden="true">{{ item.icon }}</span><span>{{ item.label }}</span><kbd v-if="!compact">{{ item.key }}</kbd>
    </button>
  </div>
</template>
<style scoped>
.result-selector{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px}.result-button{min-height:60px;padding:0 14px;border:1px solid var(--line);border-radius:14px;background:#fff;color:var(--ink);display:flex;align-items:center;justify-content:center;gap:9px;cursor:pointer;font-size:1rem;font-weight:700;touch-action:manipulation}.result-button:hover:not(:disabled){transform:translateY(-1px);box-shadow:0 5px 15px rgba(18,55,42,.1)}.result-button.selected{border-width:2px}.result-button.known.selected{border-color:#3e8962;background:#e8f5ed}.result-button.unknown.selected{border-color:var(--red);background:#fff0ef}.result-button.skipped.selected{border-color:#987226;background:#fff7df}.result-icon{font-size:1.3rem}.result-button kbd{font-size:.72rem;color:var(--muted);border:1px solid var(--line);border-radius:4px;padding:2px 5px}.compact .result-button{min-height:48px;font-size:.9rem}.result-button:disabled{cursor:not-allowed;opacity:.62}@media(max-width:374px){.result-selector{gap:8px}.result-button{min-height:56px;padding:0 8px;gap:5px}.result-button kbd{display:none}}
</style>
