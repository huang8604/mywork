<script setup lang="ts">
import { computed } from 'vue'
import { formatPhonetic } from '@/utils/formatPhonetic'
import type { PracticeItem, PracticeSession } from '@/types/domain'

export type WorksheetMode = 'cn-to-en' | 'en-to-cn'
export type WorksheetFontSize = 'small' | 'medium' | 'large'
const props = withDefaults(defineProps<{ session: PracticeSession; mode: WorksheetMode; answer?: boolean; fontSize?: WorksheetFontSize }>(), { answer: false, fontSize: 'medium' })
const fontPoints: Record<WorksheetFontSize, number> = { small: 9, medium: 11, large: 13 }
const wordFontPoints: Record<WorksheetFontSize, number> = { small: 12, medium: 15, large: 17 }
const worksheetStyle = computed<Record<string, string>>(() => ({
  '--worksheet-font-size': `${fontPoints[props.fontSize]}pt`,
  '--worksheet-word-font-size': `${wordFontPoints[props.fontSize]}pt`,
}))
const title = computed(() => props.answer ? '单词默写 · 参考答案' : '单词默写练习')
const date = computed(() => new Date(props.session.generated_at).toLocaleDateString('zh-CN'))
const modeLabel = computed(() => props.mode === 'cn-to-en' ? '看中文写英文' : '看英文写中文')
function english(item: PracticeItem): string {
  // cn-to-en recall blanks the English side (empty, no underline).
  if (!props.answer && props.mode === 'cn-to-en') return ''
  return item.word.en_word
}
function phonetic(item: PracticeItem): string {
  if (!props.answer && props.mode === 'cn-to-en') return ''
  return formatPhonetic(item.word.phonetic)
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
  <section class="worksheet" :style="worksheetStyle" :aria-label="title">
    <header class="worksheet-header"><div class="worksheet-brand"><p>拾词 · WORD MEMORY</p><h2>{{ title }}</h2><span>{{ modeLabel }} · 共 {{ session.items?.length ?? 0 }} 词</span></div><div class="sheet-mark" :class="{answer}">{{ answer?'答案':'练习' }}</div><dl><div><dt>日期</dt><dd>{{ date }}</dd></div><div v-if="!answer"><dt>姓名</dt><dd class="write-line"></dd></div><div v-if="!answer"><dt>得分</dt><dd class="score-line">____</dd></div></dl></header>
  <p class="worksheet-fit-hint no-print">标准字号已按「约 20 词 / 一页 A4」校准；词多或例句较长时浏览器会自动续页。</p>
    <table class="worksheet-table">
      <colgroup><col class="number-col"><col class="word-col"><col class="phonetic-col"><col class="meaning-col"><col class="example-col"></colgroup>
      <thead><tr class="repeat-print-header"><th colspan="5">{{ answer?'参考答案':'单词默写练习' }} · {{ modeLabel }} · {{ date }} · 第 ____ 页</th></tr><tr><th class="number-cell">序号</th><th>单词</th><th>音标</th><th>中文释义</th><th>例句</th></tr></thead>
      <tbody><tr v-for="item in session.items" :key="item.item_id"><td class="number-cell">{{ item.position }}</td><td class="word-cell">{{ english(item) }}</td><td class="phonetic-cell">{{ phonetic(item) }}</td><td class="meaning-cell">{{ chinese(item) }}</td><td class="example-cell">{{ example(item) }}</td></tr></tbody>
    </table>
    <div class="worksheet-mobile"><article v-for="item in session.items" :key="item.item_id"><span class="number-cell">{{ item.position }}</span><p class="word-cell">{{ english(item) }}</p><p class="phonetic-cell">{{ phonetic(item) }}</p><strong>{{ chinese(item) }}</strong><p class="example-cell">{{ example(item) }}</p></article></div>
    <footer class="worksheet-footer"><span>{{ answer?'核对答案后，请回到结果回录页记录本次复习结果。':'独立完成后再查看答案，并记录认识 / 不认识 / 跳过。' }}</span><span>第 ____ 页</span></footer>
  </section>
</template>
<style scoped>
.worksheet{background:#fff;color:#17243a}.worksheet-header{position:relative;display:grid;grid-template-columns:minmax(0,1fr) auto auto;align-items:center;gap:10px 18px;padding:12px 16px;border-top:4px solid #174f8f;border-bottom:1px solid #b8cde4;background:linear-gradient(135deg,#edf5fd 0%,#fff 72%)}.worksheet-brand p{margin:0;color:#41698f;font-size:.62rem;letter-spacing:.14em}.worksheet-brand h2{margin:2px 0;font:700 1.35rem Georgia,"Noto Serif SC",serif}.worksheet-brand>span{color:#5f7185;font-size:.76rem}.sheet-mark{align-self:center;padding:4px 10px;border:1px solid #2c67a4;border-radius:999px;background:#dbeafa;color:#174f8f;font-size:.72rem;font-weight:800;letter-spacing:.1em}.sheet-mark.answer{border-color:#315f91;background:#e7f1fc;color:#174f8f}.worksheet-header dl{display:flex;align-items:center;gap:14px;margin:0}.worksheet-header dl div{display:flex;align-items:end;gap:5px;min-width:72px}.worksheet-header dt{font-size:.65rem;color:#65758a}.worksheet-header dd{min-width:52px;margin:0;font-size:.78rem;font-weight:700}.write-line{height:1rem;border-bottom:1px solid #6c7d91}.score-line{letter-spacing:.06em}.worksheet-table{width:100%;border-collapse:collapse;table-layout:fixed}.number-col{width:5%}.word-col{width:18%}.phonetic-col{width:18%}.meaning-col{width:25%}.example-col{width:34%}.worksheet-table th,.worksheet-table td{border:1px solid #aabacf;padding:7px 6px;text-align:left;vertical-align:top;overflow-wrap:break-word;font-size:var(--worksheet-font-size)}.worksheet-table th{background:#dbeafb;color:#163f70;letter-spacing:.03em}.worksheet-table tbody tr:nth-child(even){background:#f5f9fe}.number-cell{text-align:center!important}.word-cell{font-family:Georgia,serif;font-weight:700;white-space:nowrap}.phonetic-cell{color:#245f9f;white-space:nowrap}.meaning-cell{font-weight:600}.example-cell{color:#44546a;font-size:.92em;line-height:1.2}.worksheet-fit-hint{margin:0 0 6px;color:#62758a;font-size:.7rem}.repeat-print-header{display:none}.worksheet-mobile{display:none;gap:12px}.worksheet-mobile article{position:relative;padding:16px;border:1px solid var(--line);border-radius:12px}.worksheet-mobile .number-cell{position:absolute;right:14px;top:14px;width:30px;height:30px;display:grid;place-items:center;border-radius:50%;background:#dbeafb}.worksheet-mobile p{color:var(--muted)}.worksheet-mobile .word-cell{margin-bottom:4px;font-size:1.35rem;color:#111}.worksheet-mobile .phonetic-cell{margin-top:0;font-size:1rem;color:#245f9f}.worksheet-footer{display:flex;justify-content:space-between;gap:20px;padding:8px 4px 0;color:#62758a;font-size:.68rem}@media(max-width:760px){.worksheet-header{padding:12px;grid-template-columns:1fr auto}.worksheet-header dl{grid-column:1/-1;justify-content:space-between;gap:8px}.worksheet-table{display:none}.worksheet-mobile{display:grid}.worksheet-footer{display:none}}
</style>
<style scoped>
.worksheet-mobile article{font-size:var(--worksheet-font-size)}
.worksheet-mobile .word-cell{font-size:var(--worksheet-word-font-size)}
.worksheet-mobile .phonetic-cell{font-size:var(--worksheet-font-size)}
</style>
