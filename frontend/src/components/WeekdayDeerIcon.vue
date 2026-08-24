<script setup lang="ts">
import fawnIcon from '@/assets/fawn-look-back-64px.png'

const props = withDefaults(defineProps<{ variant?: string; size?: number }>(), { variant: 'sun', size: 42 })
</script>

<template>
  <img
    class="weekday-deer-icon"
    :src="fawnIcon"
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
