<script setup lang="ts">
import { computed } from 'vue'
import { deerAsset } from '@/utils/deerAssets'

const props = withDefaults(defineProps<{ variant?: string; size?: number }>(), { variant: 'sun', size: 42 })
const image = computed(() => deerAsset(props.variant, 'sun'))
</script>

<template>
  <img
    class="weekday-deer-icon"
    :src="image"
    :width="props.size"
    :height="props.size"
    :data-variant="props.variant"
    role="img"
    alt="小鹿日标"
  />
  </template>

<style scoped>
.weekday-deer-icon {
  display: block;
  object-fit: contain;
}
</style>
