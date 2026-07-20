<script setup lang="ts">
import type { Word } from '@/types/domain'
defineProps<{ word: Word }>()
defineEmits<{ edit: []; remove: []; review: [] }>()
</script>
<template>
  <article class="word-card">
    <div class="word-head"><div><h3>{{ word.en_word }}</h3><p v-if="word.phonetic">{{ word.phonetic }}</p></div><span v-if="word.is_custom" class="source-pill">自定义</span></div>
    <p class="meaning">{{ word.cn_meaning }}</p><p v-if="word.example_sentence" class="example">{{ word.example_sentence }}</p>
    <div class="tag-list"><el-tag v-for="tag in word.tags" :key="tag" size="small" effect="plain">{{ tag }}</el-tag></div>
    <div class="word-meta"><span>复习 {{ word.stats.total_attempts }} 次</span><span v-if="word.stats.accuracy !== null">正确率 {{ Math.round(word.stats.accuracy*100) }}%</span></div>
    <div class="card-actions"><el-button @click="$emit('review')">复习</el-button><el-button @click="$emit('edit')">编辑</el-button><el-button type="danger" plain @click="$emit('remove')">删除</el-button></div>
  </article>
</template>
<style scoped>.word-card{padding:16px;border:1px solid var(--line);background:#fff;border-radius:14px}.word-head{display:flex;justify-content:space-between;gap:10px}.word-head h3{font:700 1.35rem Georgia,serif;margin:0}.word-head p{color:var(--green-800);margin:4px 0}.meaning{margin:13px 0 6px;font-weight:650}.example{color:var(--muted);font-style:italic}.word-meta{display:flex;gap:14px;margin:13px 0;color:var(--muted);font-size:.8rem}.card-actions{display:grid;grid-template-columns:repeat(3,1fr);gap:8px}.card-actions :deep(.el-button){margin:0;min-height:44px}</style>
