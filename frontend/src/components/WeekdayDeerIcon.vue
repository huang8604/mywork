<script setup lang="ts">
type Variant = 'sun' | 'mon' | 'tue' | 'wed' | 'thu' | 'fri' | 'sat'
const props = withDefaults(defineProps<{ variant?: string; size?: number }>(), { variant: 'sun', size: 42 })

// Original, compact deer-head marks. The antler silhouette varies by weekday so
// the icon still works when the sheet is printed without color.
const antlers: Record<Variant, string> = {
  sun: 'M19 20C15 15 13 10 14 5C10 7 9 11 11 14C7 12 5 9 5 6C3 10 5 17 12 21M29 20C33 15 35 10 34 5C38 7 39 11 37 14C41 12 43 9 43 6C45 10 43 17 36 21',
  mon: 'M18 21C13 17 10 11 11 5C8 7 7 12 10 16C6 15 4 12 4 9C2 14 5 20 13 23M30 21C35 17 38 11 37 5C40 7 41 12 38 16C42 15 44 12 44 9C46 14 43 20 35 23',
  tue: 'M18 21C13 19 11 13 13 6C9 8 8 12 10 16C6 15 5 12 6 8C2 13 5 20 13 23M30 21C35 19 37 13 35 6C39 8 40 12 38 16C42 15 43 12 42 8C46 13 43 20 35 23',
  wed: 'M19 20C16 15 14 10 16 4C11 6 9 11 12 15C8 14 6 11 6 7C3 12 6 18 13 22M29 20C32 15 34 10 32 4C37 6 39 11 36 15C40 14 42 11 42 7C45 12 42 18 35 22',
  thu: 'M20 21C17 16 16 10 19 5C14 5 11 9 13 14C9 13 8 10 9 6C5 11 7 18 14 23M28 21C31 16 32 10 29 5C34 5 37 9 35 14C39 13 40 10 39 6C43 11 41 18 34 23',
  fri: 'M19 20C15 16 12 11 13 5C9 7 8 11 11 15C7 14 5 11 5 8C2 13 5 19 13 22M29 20C33 16 36 11 35 5C39 7 40 11 37 15C41 14 43 11 43 8C46 13 43 19 35 22',
  sat: 'M18 21C12 18 9 12 12 5C7 7 6 13 9 17C5 16 3 13 4 9C0 14 4 21 13 24M30 21C36 18 39 12 36 5C41 7 42 13 39 17C43 16 45 13 44 9C48 14 44 21 35 24',
}
const key = (props.variant in antlers ? props.variant : 'sun') as Variant
</script>

<template>
  <svg class="weekday-deer-icon" :width="size" :height="size" viewBox="0 0 48 48" role="img" aria-label="小鹿日标">
    <path :d="antlers[key]" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round" />
    <path d="M14 22C14 16 18 13 24 13C30 13 34 16 34 22V30C34 37 30 41 24 41C18 41 14 37 14 30Z" fill="currentColor" opacity=".92" />
    <path d="M14 23C10 21 8 23 10 27C11 29 13 29 15 28M34 23C38 21 40 23 38 27C37 29 35 29 33 28" fill="currentColor" opacity=".72" />
    <circle cx="20" cy="26" r="1.7" fill="#fff" /><circle cx="28" cy="26" r="1.7" fill="#fff" />
    <path d="M21 33C23 35 25 35 27 33" fill="none" stroke="#fff" stroke-width="1.5" stroke-linecap="round" />
  </svg>
</template>
