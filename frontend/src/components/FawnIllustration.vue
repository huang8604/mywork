<script setup lang="ts">
import { computed } from 'vue'
import { deerAsset } from '@/utils/deerAssets'

const props = withDefaults(defineProps<{ variant?: string; width?: number }>(), {
  variant: 'mon',
  width: 88,
})
const image = computed(() => deerAsset(props.variant))
</script>

<template>
  <img
    class="fawn-illustration"
    :src="image"
    :data-variant="props.variant"
    :width="props.width"
    :height="props.width"
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
