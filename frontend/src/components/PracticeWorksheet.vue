<script setup lang="ts">
import { computed } from 'vue'
import { formatPhonetic } from '@/utils/formatPhonetic'
import { worksheetTheme } from '@/utils/worksheetTheme'
import type { PracticeItem, PracticeSession } from '@/types/domain'

export type WorksheetMode = 'cn-to-en' | 'en-to-cn'
export type WorksheetFontSize = 'small' | 'medium' | 'large'
const props = withDefaults(defineProps<{ session: PracticeSession; mode: WorksheetMode; answer?: boolean; fontSize?: WorksheetFontSize }>(), { answer: false, fontSize: 'medium' })
const fontPoints: Record<WorksheetFontSize, number> = { small: 9, medium: 11, large: 13 }
const wordFontPoints: Record<WorksheetFontSize, number> = { small: 12, medium: 15, large: 17 }
const theme = computed(() => worksheetTheme(props.session.generated_at))
const worksheetStyle = computed<Record<string, string>>(() => ({
  '--worksheet-font-size': `${fontPoints[props.fontSize]}pt`,
  '--worksheet-word-font-size': `${wordFontPoints[props.fontSize]}pt`,
  '--ws-primary': theme.value.primary,
  '--ws-deep': theme.value.deep,
  '--ws-accent': theme.value.accent,
}))
const title = computed(() => props.answer ? '单词默写 · 参考答案' : '单词默写练习')
const count = computed(() => props.session.items?.length ?? 0)
const dateText = computed(() => {
  const d = new Date(props.session.generated_at)
  if (Number.isNaN(d.getTime())) return ''
  const y = d.getFullYear()
  const m = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  return `${y}年${m}月${day}日`
})
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
    <header class="ws-hero">
      <div class="ws-hero-title">
        <p class="ws-eyebrow">拾词 · WORD MEMORY</p>
        <h2>{{ title }}</h2>
        <p class="ws-subtitle">{{ modeLabel }} · 共 {{ count }} 词 · {{ theme.weekdayName }}</p>
      </div>
      <div class="ws-date-card">
        <span class="ws-date-label">DATE / 日期</span>
        <span class="ws-date-value">{{ dateText }}</span>
        <span class="ws-weekday">{{ theme.weekdayName }}</span>
      </div>
    </header>
    <div v-if="!answer" class="ws-meta-row no-print">
      <span class="ws-meta-item"><small>姓名</small><span class="write-line"></span></span>
      <span class="ws-meta-item"><small>得分</small><span class="score-line">____</span></span>
      <span class="ws-sheet-mark">练习</span>
    </div>
    <p class="worksheet-fit-hint no-print">标准字号已按「约 20 词 / 一页 A4」校准；主题色按复习表日期(周{{ theme.weekdayName.replace('周','') }})变化。词多或例句较长时浏览器会自动续页。</p>
    <table class="worksheet-table">
      <colgroup><col class="number-col"><col class="word-col"><col class="phonetic-col"><col class="meaning-col"><col class="example-col"></colgroup>
      <thead><tr class="repeat-print-header"><th colspan="5">{{ answer?'参考答案':'单词默写练习' }} · {{ modeLabel }} · {{ dateText }} · {{ theme.weekdayName }} · 第 ____ 页</th></tr><tr><th class="number-cell">序号</th><th>单词</th><th>音标</th><th>中文释义</th><th>例句</th></tr></thead>
      <tbody><tr v-for="item in session.items" :key="item.item_id"><td class="number-cell">{{ item.position }}</td><td class="word-cell">{{ english(item) }}</td><td class="phonetic-cell">{{ phonetic(item) }}</td><td class="meaning-cell">{{ chinese(item) }}</td><td class="example-cell">{{ example(item) }}</td></tr></tbody>
    </table>
    <div class="worksheet-mobile"><article v-for="item in session.items" :key="item.item_id"><span class="number-cell">{{ item.position }}</span><p class="word-cell">{{ english(item) }}</p><p class="phonetic-cell">{{ phonetic(item) }}</p><strong>{{ chinese(item) }}</strong><p class="example-cell">{{ example(item) }}</p></article></div>
    <footer class="worksheet-footer"><span>{{ answer?'核对答案后，请回到结果回录页记录本次复习结果。':'独立完成后再查看答案，并记录认识 / 不认识 / 跳过。' }}</span><span>第 ____ 页</span></footer>
  </section>
</template>
<style scoped>
.worksheet{background:#fff;color:#17243a;-webkit-print-color-adjust:exact;print-color-adjust:exact}
.ws-hero{display:flex;align-items:center;justify-content:space-between;gap:12px 18px;min-height:64px;padding:12px 16px;color:#fff;background:var(--ws-deep);background:linear-gradient(120deg,var(--ws-deep),var(--ws-primary));border-bottom:7px solid var(--ws-accent);border-radius:10px 10px 0 0}
.ws-hero-title .ws-eyebrow{margin:0;color:#fff;opacity:.78;font-size:.62rem;font-weight:700;letter-spacing:.14em}
.ws-hero-title h2{margin:2px 0;font:700 1.35rem Georgia,"Noto Serif SC",serif;color:#fff}
.ws-hero-title .ws-subtitle{margin:0;color:#fff;opacity:.88;font-size:.76rem}
.ws-date-card{flex:0 0 auto;min-width:96px;padding:6px 12px;text-align:center;color:var(--ws-deep);background:rgba(255,255,255,.94);border-radius:8px;box-shadow:0 2px 6px rgba(0,0,0,.12);display:grid;gap:1px}
.ws-date-card .ws-date-label{color:var(--muted);font-size:.6rem;font-weight:700;letter-spacing:1.2px}
.ws-date-card .ws-date-value{font-size:.82rem;font-weight:800;white-space:nowrap}
.ws-date-card .ws-weekday{font-size:.68rem;font-weight:700;color:var(--ws-primary)}
.ws-meta-row{display:flex;align-items:center;gap:16px;padding:8px 4px;color:#62758a;font-size:.74rem}
.ws-meta-item{display:flex;align-items:end;gap:5px}
.ws-meta-item small{color:#65758a}
.ws-sheet-mark{margin-left:auto;padding:3px 10px;border:1px solid var(--ws-primary);border-radius:999px;background:rgba(255,255,255,.6);color:var(--ws-deep);font-size:.68rem;font-weight:800;letter-spacing:.1em}
.worksheet-table{width:100%;border-collapse:collapse;table-layout:fixed}
.number-col{width:5%}.word-col{width:18%}.phonetic-col{width:18%}.meaning-col{width:25%}.example-col{width:34%}
.worksheet-table th,.worksheet-table td{border:1px solid #aabacf;padding:7px 6px;text-align:left;vertical-align:top;overflow-wrap:break-word;font-size:var(--worksheet-font-size)}
.worksheet-table th{background:var(--ws-primary);color:#fff;letter-spacing:.03em}
.worksheet-table tbody tr:nth-child(even){background:#f6f9fd}
.number-cell{text-align:center!important}
.word-cell{font-family:Georgia,serif;font-weight:700;white-space:nowrap}
.phonetic-cell{color:#4a6075;white-space:nowrap}
.meaning-cell{font-weight:600}
.example-cell{color:#44546a;font-size:.92em;line-height:1.2}
.worksheet-fit-hint{margin:0 0 6px;color:#62758a;font-size:.7rem}
.repeat-print-header{display:none}
.worksheet-mobile{display:none;gap:12px}
.worksheet-mobile article{position:relative;padding:16px;border:1px solid var(--line);border-radius:12px}
.worksheet-mobile .number-cell{position:absolute;right:14px;top:14px;width:30px;height:30px;display:grid;place-items:center;border-radius:50%;background:var(--ws-primary);color:#fff}
.worksheet-mobile p{color:var(--muted)}
.worksheet-mobile .word-cell{margin-bottom:4px;font-size:1.35rem;color:#111}
.worksheet-mobile .phonetic-cell{margin-top:0;font-size:1rem;color:#4a6075}
.worksheet-footer{display:flex;justify-content:space-between;gap:20px;padding:8px 4px 0;color:#62758a;font-size:.68rem}
.write-line{display:inline-block;width:90px;height:1rem;border-bottom:1px solid #6c7d91}
.score-line{letter-spacing:.06em}
@media(max-width:760px){.ws-hero{padding:12px}.ws-date-card{display:none}.worksheet-table{display:none}.worksheet-mobile{display:grid}.worksheet-footer{display:none}}
</style>
<style scoped>
.worksheet-mobile article{font-size:var(--worksheet-font-size)}
.worksheet-mobile .word-cell{font-size:var(--worksheet-word-font-size)}
.worksheet-mobile .phonetic-cell{font-size:var(--worksheet-font-size)}
</style>
