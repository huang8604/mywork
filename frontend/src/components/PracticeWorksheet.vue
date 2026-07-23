<script setup lang="ts">
import { computed } from 'vue'
import { formatPhonetic } from '@/utils/formatPhonetic'
import type { PracticeItem, PracticeSession } from '@/types/domain'

export type WorksheetMode = 'cn-to-en' | 'en-to-cn'
const props = defineProps<{ session: PracticeSession; mode: WorksheetMode; answer?: boolean }>()
const title = computed(() => props.answer ? '单词默写 · 参考答案' : '单词默写练习')
const date = computed(() => new Date(props.session.generated_at).toLocaleDateString('zh-CN'))
const modeLabel = computed(() => props.mode === 'cn-to-en' ? '看中文写英文' : '看英文写中文')
function wordCell(item: PracticeItem): string {
  // cn-to-en recall blanks the English side (empty, no underline).
  if (!props.answer && props.mode === 'cn-to-en') return ''
  const ph = formatPhonetic(item.word.phonetic)
  return ph ? `${item.word.en_word} ${ph}` : item.word.en_word
}
function chinese(item: PracticeItem): string {
  // en-to-cn recall blanks the Chinese side (empty, no underline).
  return (props.answer || props.mode !== 'en-to-cn') ? (item.word.cn_meaning || '') : ''
}
function example(item: PracticeItem): string {
  return item.word.example_sentence || '—'
}
</script>
<template>
  <section class="worksheet" :aria-label="title">
    <header class="worksheet-header"><div class="worksheet-brand"><p>拾词 · WORD MEMORY</p><h2>{{ title }}</h2><span>{{ modeLabel }} · 共 {{ session.items?.length ?? 0 }} 词</span></div><div class="sheet-mark" :class="{answer}">{{ answer?'答案':'练习' }}</div><dl><div><dt>日期</dt><dd>{{ date }}</dd></div><div v-if="!answer"><dt>姓名</dt><dd class="write-line"></dd></div><div v-if="!answer"><dt>得分</dt><dd class="score-line">____</dd></div></dl></header>
    <table class="worksheet-table">
      <thead><tr class="repeat-print-header"><th colspan="4">{{ answer?'参考答案':'单词默写练习' }} · {{ modeLabel }} · {{ date }} · 第 ____ 页</th></tr><tr><th class="number-cell">序号</th><th>单词 / 音标</th><th>中文释义</th><th>例句</th></tr></thead>
      <tbody><tr v-for="item in session.items" :key="item.item_id"><td class="number-cell">{{ item.position }}</td><td class="word-cell">{{ wordCell(item) }}</td><td>{{ chinese(item) }}</td><td class="example-cell">{{ example(item) }}</td></tr></tbody>
    </table>
    <div class="worksheet-mobile"><article v-for="item in session.items" :key="item.item_id"><span class="number-cell">{{ item.position }}</span><p class="word-cell">{{ wordCell(item) }}</p><strong>{{ chinese(item) }}</strong><p class="example-cell">{{ example(item) }}</p></article></div>
    <footer class="worksheet-footer"><span>{{ answer?'核对答案后，请回到结果回录页记录本次复习结果。':'独立完成后再查看答案，并记录认识 / 不认识 / 跳过。' }}</span><span>第 ____ 页</span></footer>
  </section>
</template>
<style scoped>
.worksheet{background:#fff;color:#17251f}.worksheet-header{position:relative;display:grid;grid-template-columns:minmax(0,1fr) auto;gap:16px 28px;padding:22px 24px;border-top:6px solid #173b2d;border-bottom:1px solid #bfd0c7;background:linear-gradient(135deg,#f6faf7 0%,#fff 68%)}.worksheet-brand p{margin:0;color:#486559;font-size:.7rem;letter-spacing:.16em}.worksheet-brand h2{margin:5px 0 3px;font:700 1.7rem Georgia,"Noto Serif SC",serif}.worksheet-brand>span{color:#65736c;font-size:.82rem}.sheet-mark{align-self:start;padding:6px 13px;border:1px solid #2e684f;border-radius:999px;background:#e4f1e9;color:#24553f;font-size:.78rem;font-weight:800;letter-spacing:.12em}.sheet-mark.answer{border-color:#9a6a22;background:#fff2d5;color:#7a5118}.worksheet-header dl{grid-column:1/-1;display:flex;gap:26px;margin:0;padding-top:7px}.worksheet-header dl div{display:flex;align-items:end;gap:8px;min-width:100px}.worksheet-header dt{font-size:.72rem;color:#65736c}.worksheet-header dd{min-width:70px;margin:0;font-weight:700}.write-line{height:1.2rem;border-bottom:1px solid #6b7872}.score-line{letter-spacing:.08em}.worksheet-table{width:100%;border-collapse:collapse}.worksheet-table th,.worksheet-table td{border:1px solid #aebbb4;padding:10px 9px;text-align:left;vertical-align:top;overflow-wrap:anywhere}.worksheet-table th{background:#e9f1ec;color:#264c3c;font-size:.78rem;letter-spacing:.04em}.worksheet-table tbody tr:nth-child(even){background:#f9fbfa}.number-cell{text-align:center!important;width:48px}.word-cell{font-family:Georgia,serif;font-weight:700;white-space:nowrap}.example-cell{min-width:190px}.repeat-print-header{display:none}.worksheet-mobile{display:none;gap:12px}.worksheet-mobile article{position:relative;padding:16px;border:1px solid var(--line);border-radius:12px}.worksheet-mobile .number-cell{position:absolute;right:14px;top:14px;width:30px;height:30px;display:grid;place-items:center;border-radius:50%;background:var(--green-100)}.worksheet-mobile p{color:var(--muted)}.worksheet-mobile .word-cell{font-size:1.35rem;color:#111}.worksheet-footer{display:flex;justify-content:space-between;gap:20px;padding:12px 4px 0;color:#65736c;font-size:.72rem}@media(max-width:639px){.worksheet-header{padding:14px;grid-template-columns:1fr auto}.worksheet-header dl{justify-content:space-between;gap:10px}.worksheet-table{display:none}.worksheet-mobile{display:grid}.worksheet-footer{display:none}}
</style>
