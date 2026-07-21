<script setup lang="ts">
import { computed } from 'vue'
import { blankWord } from '@/utils/blankWord'
import type { PracticeItem, PracticeSession } from '@/types/domain'

export type WorksheetMode = 'cn-to-en' | 'en-to-cn' | 'cloze'
const props = defineProps<{ session: PracticeSession; mode: WorksheetMode; answer?: boolean }>()
const title = computed(() => props.answer ? '单词复习表 · 答案' : '单词复习表')
const date = computed(() => new Date(props.session.generated_at).toLocaleDateString('zh-CN'))
function english(item: PracticeItem) { return props.answer || props.mode === 'en-to-cn' ? item.word.en_word : '________________' }
function chinese(item: PracticeItem) { return props.answer || props.mode !== 'en-to-cn' ? item.word.cn_meaning : '________________________' }
function example(item: PracticeItem) { return props.answer ? (item.word.example_sentence || '—') : (blankWord(item.word.example_sentence, item.word.en_word).text || '—') }
function missing(item: PracticeItem) { return !props.answer && Boolean(item.word.example_sentence) && !blankWord(item.word.example_sentence, item.word.en_word).found }
</script>
<template>
  <section class="worksheet" :aria-label="title">
    <header class="worksheet-header"><div><p>拾词 · WORD MEMORY</p><h2>{{ title }}</h2></div><dl><div><dt>会话</dt><dd>#{{ session.session_id }}</dd></div><div><dt>日期</dt><dd>{{ date }}</dd></div><div><dt>页码</dt><dd>____ / ____</dd></div></dl></header>
    <table class="worksheet-table">
      <thead><tr class="repeat-print-header"><th colspan="5">会话 #{{ session.session_id }} · {{ date }} · 页码 ____ / ____</th></tr><tr><th class="number-cell">序号</th><th>英文单词</th><th>音标</th><th>中文释义</th><th>例句{{ answer?'':'填空' }}</th></tr></thead>
      <tbody><tr v-for="item in session.items" :key="item.item_id"><td class="number-cell">{{ item.position }}</td><td class="english-cell">{{ english(item) }}</td><td>{{ item.word.phonetic || '—' }}</td><td>{{ chinese(item) }}</td><td class="example-cell">{{ example(item) }}<small v-if="missing(item)" class="blank-warning">未找到目标词，已保留原句</small></td></tr></tbody>
    </table>
    <div class="worksheet-mobile"><article v-for="item in session.items" :key="item.item_id"><span class="number-cell">{{ item.position }}</span><p class="english-cell">{{ english(item) }}</p><p>{{ item.word.phonetic || '—' }}</p><strong>{{ chinese(item) }}</strong><p class="example-cell">{{ example(item) }}</p><small v-if="missing(item)" class="blank-warning">未找到目标词，已保留原句</small></article></div>
  </section>
</template>
<style scoped>
.worksheet{background:#fff;color:#111}.worksheet-header{display:flex;justify-content:space-between;gap:20px;padding:18px 20px;border-bottom:2px solid #173b2d}.worksheet-header p{margin:0;color:#486559;font-size:.7rem;letter-spacing:.14em}.worksheet-header h2{margin:4px 0 0;font-family:Georgia,"Noto Serif SC",serif}.worksheet-header dl{display:flex;gap:18px;margin:0}.worksheet-header dl div{display:grid;gap:3px}.worksheet-header dt{font-size:.7rem;color:#65736c}.worksheet-header dd{margin:0;font-weight:700}.worksheet-table{width:100%;border-collapse:collapse}.worksheet-table th,.worksheet-table td{border:1px solid #9ca7a1;padding:9px 8px;text-align:left;vertical-align:top;overflow-wrap:anywhere}.worksheet-table th{background:#edf3ef;font-size:.78rem}.number-cell{text-align:center!important;width:48px}.english-cell{font-family:Georgia,serif;font-weight:700}.example-cell{min-width:190px}.repeat-print-header{display:none}.blank-warning{display:block;margin-top:5px;color:#986a13}.worksheet-mobile{display:none;gap:12px}.worksheet-mobile article{position:relative;padding:16px;border:1px solid var(--line);border-radius:12px}.worksheet-mobile .number-cell{position:absolute;right:14px;top:14px;width:30px;height:30px;display:grid;place-items:center;border-radius:50%;background:var(--green-100)}.worksheet-mobile p{color:var(--muted)}.worksheet-mobile .english-cell{font-size:1.35rem;color:#111}@media(max-width:639px){.worksheet-header{padding:14px;display:grid}.worksheet-header dl{justify-content:space-between}.worksheet-table{display:none}.worksheet-mobile{display:grid}}
</style>
