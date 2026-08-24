<script setup lang="ts">
import fawnIcon from '@/assets/fawn-look-back-64px.png'

const props = withDefaults(defineProps<{ variant?: string; width?: number }>(), {
  variant: 'mon',
  width: 84,
})
</script>

<template>
  <img
    class="fawn-illustration"
    :src="fawnIcon"
    :data-variant="props.variant"
    :width="props.width"
    :height="Math.round(props.width * 0.75)"
    role="img"
    alt="星期小鹿插图"
  />
</template>

<style scoped>
.fawn-illustration {
  display: block;
  object-fit: contain;
}
</style>
