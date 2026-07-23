<script setup lang="ts">
import type { Word } from '@/types/domain'
import { formatPhonetic } from '@/utils/formatPhonetic'
defineProps<{ word: Word }>()
defineEmits<{ edit: []; remove: []; review: [] }>()
const reviewedAt = (value: string | null) => value ? new Date(value).toLocaleString('zh-CN') : '尚未背诵'
</script>
<template>
  <article class="word-card">
    <div class="word-head"><div><h3>{{ word.en_word }}</h3><p v-if="word.phonetic">{{ formatPhonetic(word.phonetic) }}</p></div><span v-if="word.is_custom" class="source-pill">自定义</span></div>
    <p class="meaning">{{ word.cn_meaning }}</p><p v-if="word.example_sentence" class="example">{{ word.example_sentence }}</p>
    <div class="tag-list"><el-tag v-for="tag in word.tags" :key="tag" size="small" effect="plain">{{ tag }}</el-tag></div>
    <div class="word-stats"><span class="known">成功 <strong>{{ word.stats.known_count ?? 0 }}</strong></span><span class="unknown">失败 <strong>{{ word.stats.unknown_count ?? 0 }}</strong></span><span>上次背诵 {{ reviewedAt(word.stats.last_reviewed_at ?? null) }}</span></div>
    <div class="card-actions"><el-button @click="$emit('review')">复习</el-button><el-button @click="$emit('edit')">编辑</el-button><el-button type="danger" plain @click="$emit('remove')">删除</el-button></div>
  </article>
</template>
<style scoped>.word-card{padding:16px;border:1px solid var(--line);background:#fff;border-radius:14px}.word-head{display:flex;justify-content:space-between;gap:10px}.word-head h3{font:700 1.35rem Georgia,serif;margin:0}.word-head p{color:var(--green-800);margin:4px 0}.meaning{margin:13px 0 6px;font-weight:650}.example{color:var(--muted);font-style:italic}.word-stats{display:flex;gap:8px 14px;flex-wrap:wrap;margin:13px 0;color:var(--muted);font-size:.8rem}.word-stats .known strong{color:#287650}.word-stats .unknown strong{color:#b44c43}.card-actions{display:grid;grid-template-columns:repeat(3,1fr);gap:8px}.card-actions :deep(.el-button){margin:0;min-height:44px}</style>
