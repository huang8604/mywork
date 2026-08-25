<script setup lang="ts">
import { ref } from 'vue'
import type { Word } from '@/types/domain'
import { formatPhonetic } from '@/utils/formatPhonetic'
import WordCard from './WordCard.vue'
const props = defineProps<{ words: Word[] }>()
const emit = defineEmits<{ edit: [word: Word]; remove: [word: Word]; reset: [word: Word]; review: [word: Word]; playAudio: [word: Word]; generateAudio: [word: Word]; 'selection-change': [words: Word[]] }>()
const accuracy = (word: Word) => word.stats.accuracy === null ? '—' : `${Math.round(word.stats.accuracy * 100)}%`
const lastReviewed = (word: Word) => word.stats.last_reviewed_at ? new Date(word.stats.last_reviewed_at).toLocaleString('zh-CN') : '尚未背诵'
const tableRef = ref()
const mobileSelected = ref<Set<number>>(new Set())
function onTableSelection(rows: Word[]) { mobileSelected.value = new Set(rows.map(r => r.id)); emit('selection-change', rows) }
function toggleMobile(word: Word, checked: boolean) {
  const next = new Set(mobileSelected.value)
  if (checked) next.add(word.id); else next.delete(word.id)
  mobileSelected.value = next
  emit('selection-change', props.words.filter(w => next.has(w.id)))
}
function clearSelection() {
  mobileSelected.value = new Set()
  tableRef.value?.clearSelection?.()
  emit('selection-change', [])
}
defineExpose({ clearSelection })
</script>
<template>
  <div class="desktop-word-table local-scroll">
    <el-table ref="tableRef" :data="words" row-key="id" style="min-width:1120px" @selection-change="onTableSelection">
      <el-table-column type="selection" width="42" />
      <el-table-column label="单词" min-width="175"><template #default="{row}"><strong class="table-word">{{ row.en_word }}</strong><small v-if="row.phonetic">{{ formatPhonetic(row.phonetic) }}</small></template></el-table-column>
      <el-table-column prop="cn_meaning" label="中文释义" min-width="220" show-overflow-tooltip />
      <el-table-column label="标签" min-width="150"><template #default="{row}"><div class="tag-list"><el-tag v-for="tag in row.tags" :key="tag" size="small" effect="plain">{{ tag }}</el-tag></div></template></el-table-column>
      <el-table-column label="正确率" width="90"><template #default="{row}">{{ accuracy(row) }}</template></el-table-column>
      <el-table-column label="成功 / 失败" width="120"><template #default="{row}"><span class="review-count known">{{ row.stats.known_count }}</span><span class="count-divider"> / </span><span class="review-count unknown">{{ row.stats.unknown_count }}</span></template></el-table-column>
      <el-table-column label="音频" width="150"><template #default="{row}"><el-tag v-if="row.audio_path" size="small" type="success" effect="plain">{{ row.audio_provider === 'volc' ? '豆包' : row.audio_provider === 'mimo' ? 'Mimo' : '已生成' }}</el-tag><small v-if="row.audio_model" class="audio-model">{{ row.audio_model }}</small><el-tag v-else size="small" type="info" effect="plain">未生成</el-tag></template></el-table-column>
      <el-table-column label="上次背诵" width="175"><template #default="{row}">{{ lastReviewed(row) }}</template></el-table-column>
      <el-table-column label="操作" width="380" fixed="right"><template #default="{row}"><el-button link type="primary" :disabled="!row.audio_path" @click="$emit('playAudio',row)">播放</el-button><el-button link @click="$emit('generateAudio',row)">{{ row.audio_path?'重生成':'生成音频' }}</el-button><el-button link type="primary" @click="$emit('review',row)">复习</el-button><el-button link @click="$emit('reset',row)">设为新词</el-button><el-button link @click="$emit('edit',row)">编辑</el-button><el-button link type="danger" @click="$emit('remove',row)">删除</el-button></template></el-table-column>
    </el-table>
  </div>
  <div class="mobile-word-cards"><WordCard v-for="word in words" :key="word.id" :word="word" :selected="mobileSelected.has(word.id)" @toggle="(c:boolean)=>toggleMobile(word,c)" @edit="$emit('edit',word)" @remove="$emit('remove',word)" @reset="$emit('reset',word)" @review="$emit('review',word)" @play-audio="$emit('playAudio',word)" @generate-audio="$emit('generateAudio',word)" /></div>
</template>
<style scoped>.table-word{display:block;font-family:Georgia,serif;font-size:1.05rem}.table-word+small{display:block;color:var(--green-800);margin-top:4px}.audio-model{display:block;margin-top:3px;color:var(--muted);font-size:.68rem;white-space:normal;word-break:break-all}.review-count{font-weight:800}.review-count.known{color:#287650}.review-count.unknown{color:#b44c43}.count-divider{color:var(--muted)}.mobile-word-cards{display:none;gap:12px}@media(max-width:639px){.desktop-word-table{display:none}.mobile-word-cards{display:grid}}</style>
