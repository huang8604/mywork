<script setup lang="ts">
import type { AsyncPhase } from '@/types/domain'
import type { ApiError } from '@/api/client'
defineProps<{ phase: AsyncPhase; error?: ApiError | null; emptyText?: string }>()
defineEmits<{ retry: [] }>()
</script>
<template>
  <div v-if="phase === 'loading'" class="async-state" role="status" aria-live="polite"><el-skeleton :rows="4" animated /></div>
  <div v-else-if="phase === 'error'" class="async-state error-box" role="alert">
    <strong>加载失败</strong><p>{{ error?.message || '暂时无法加载数据' }}</p>
    <span v-if="error?.requestId" class="request-id">请求编号：{{ error.requestId }}</span>
    <el-button type="primary" @click="$emit('retry')">重试</el-button>
  </div>
  <div v-else-if="phase === 'empty'" class="async-state empty-state">
    <span class="empty-illustration" aria-hidden="true">☁</span><p>{{ emptyText || '这里还没有数据' }}</p><slot name="empty-action" />
  </div>
  <slot v-else />
</template>
<style scoped>.async-state{padding:24px}.empty-state{text-align:center;color:var(--muted)}.error-box p{margin:8px 0}.request-id{margin-bottom:12px}</style>
