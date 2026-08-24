<script setup lang="ts">
// 手绘 Bambi 风格小鹿插图：一天只显示一个姿势，随星期变化。
// 共享躯干 + 姿势差异集中在 transform 与少量覆盖元素；花朵花心引用
// --ws-accent 主题色，彩打随星期换色，黑白打印仍能读出剪影。
type Variant = 'sun' | 'mon' | 'tue' | 'wed' | 'thu' | 'fri' | 'sat'
const props = withDefaults(defineProps<{ variant?: string; width?: number }>(), { variant: 'mon', width: 84 })

interface Pose {
  fawn?: string // 整体（躯干+头）变换
  head?: string // 头组变换
  closed?: boolean // 眼睛画成安睡弧线
  extra?: 'sniff' | 'prance' | 'stretch' | 'rest'
}
const POSES: Record<Variant, Pose> = {
  mon: {},
  tue: { head: 'rotate(-12 36 36)' },
  wed: { head: 'translate(2 13) rotate(10 36 36)', extra: 'sniff' },
  thu: { head: 'translate(26 -3) rotate(30 36 36)' },
  fri: { fawn: 'rotate(-6 58 56)', extra: 'prance' },
  sat: { fawn: 'rotate(9 62 58)', head: 'translate(3 10) rotate(-4 36 36)', extra: 'stretch' },
  sun: { head: 'translate(14 26) rotate(24 36 36)', closed: true, extra: 'rest' },
}
const key = (props.variant in POSES ? props.variant : 'mon') as Variant
const pose = POSES[key]
</script>

<template>
  <svg class="fawn-illustration" :data-variant="key" :width="width" :height="Math.round(width * 0.75)" viewBox="0 0 120 90" role="img" aria-label="星期小鹿插图">
    <!-- 童话森林背景：柔光、光斑、苔藓地、野花 -->
    <ellipse cx="62" cy="60" rx="54" ry="30" fill="#fdf3dd" opacity=".55" />
    <path d="M20 12 L44 44 M34 8 L52 40 M50 10 L62 38" stroke="#f7d9a0" stroke-width="3" stroke-linecap="round" opacity=".45" />
    <ellipse cx="60" cy="83" rx="42" ry="6" fill="#cfe3bd" opacity=".65" />
    <path d="M18 82 L16 76 M21 82 L22 75 M98 83 L96 77 M101 83 L103 76" stroke="#9db98a" stroke-width="1.4" stroke-linecap="round" opacity=".8" fill="none" />
    <g>
      <circle cx="14" cy="77" r="2.2" fill="#f9c6d0" /><circle cx="18" cy="79" r="2.2" fill="#f9c6d0" /><circle cx="16" cy="81.5" r="2.2" fill="#f9c6d0" /><circle cx="12" cy="81" r="2.2" fill="#f9c6d0" /><circle cx="15.5" cy="79.5" r="1.7" fill="#f3c53d" />
      <circle cx="104" cy="79" r="2" fill="#fde8c0" /><circle cx="108" cy="80.5" r="2" fill="#fde8c0" /><circle cx="106" cy="83" r="2" fill="#fde8c0" /><circle cx="106" cy="80.4" r="1.5" fill="var(--ws-accent, #fbbf24)" />
    </g>
    <!-- 周三：低头嗅的大花 -->
    <g v-if="pose.extra === 'sniff'">
      <circle cx="26" cy="60" r="3" fill="#f9c6d0" /><circle cx="21" cy="62" r="2.6" fill="#f9c6d0" /><circle cx="31" cy="62" r="2.6" fill="#f9c6d0" /><circle cx="26" cy="64" r="2.6" fill="#f9c6d0" /><circle cx="26" cy="61.8" r="2" fill="#f3c53d" />
    </g>
    <!-- 周五：小跳步动态线 -->
    <path v-if="pose.extra === 'prance'" d="M86 44 q6 -4 5 -11 M92 52 q7 -2 8 -9" stroke="#f7d9a0" stroke-width="2" stroke-linecap="round" fill="none" opacity=".7" />

    <g class="fawn" :transform="pose.fawn || ''">
      <!-- 细长腿（周日卧姿收起） -->
      <path v-if="pose.extra !== 'rest'" d="M44 64 L41 81 M50 65 L49 81 M68 64 L72 81 M74 62 L78 80" stroke="#b5793f" stroke-width="2.6" stroke-linecap="round" fill="none" />
      <path v-else d="M40 68 L58 68 M74 66 L90 66" stroke="#b5793f" stroke-width="2.6" stroke-linecap="round" fill="none" />
      <!-- 躯干 / 奶油胸腹 / 尾巴 / 白色梅花斑 -->
      <ellipse cx="58" cy="57" rx="20" ry="11.5" fill="#d9a066" />
      <ellipse cx="58" cy="61" rx="12.5" ry="6" fill="#f6e7cd" />
      <ellipse cx="43" cy="57" rx="4.5" ry="6" fill="#f6e7cd" />
      <circle cx="77" cy="51" r="3.4" fill="#fdf6ea" />
      <g fill="#fdf6ea">
        <circle cx="52" cy="51" r="2" /><circle cx="59" cy="49" r="1.7" /><circle cx="66" cy="51.5" r="1.9" /><circle cx="55" cy="54.5" r="1.4" /><circle cx="62" cy="55" r="1.5" />
      </g>
      <!-- 头组：黑耳尖大耳 / 大眼 / 口鼻 / 腮红 -->
      <g :transform="pose.head || ''">
        <path d="M30 29 C25 21 19 19 16.5 22 C14.5 25 18 30 25 32 Z" fill="#d9a066" />
        <path d="M27 28.4 C24 24 20.5 22.6 19 24 C17.8 25.4 20 28.6 24.6 30 Z" fill="#43301c" />
        <path d="M40 27 C44 19 50 17.5 52.5 20.5 C54.3 23.4 50.8 28.8 44 31 Z" fill="#d9a066" />
        <path d="M42.8 26.4 C45.8 21.6 49.3 20.4 50.7 21.9 C51.8 23.4 49.4 26.9 45 28.4 Z" fill="#43301c" />
        <circle cx="36" cy="37" r="9.6" fill="#d9a066" />
        <ellipse cx="29.5" cy="40" rx="4.8" ry="3.6" fill="#f6e7cd" />
        <circle cx="26.6" cy="39" r="1.5" fill="#43301c" />
        <path d="M27.5 42.2 q2 1.8 4 0.4" fill="none" stroke="#43301c" stroke-width="1.1" stroke-linecap="round" />
        <g v-if="!pose.closed">
          <circle cx="33" cy="36" r="2.3" fill="#3d2817" /><circle cx="33.8" cy="35.2" r="0.8" fill="#fff" />
          <circle cx="40" cy="36.4" r="2.3" fill="#3d2817" /><circle cx="40.8" cy="35.6" r="0.8" fill="#fff" />
        </g>
        <path v-else d="M31.4 36.2 q1.6 1.6 3.2 0 M38.4 36.6 q1.6 1.6 3.2 0" stroke="#3d2817" stroke-width="1.5" stroke-linecap="round" fill="none" />
        <ellipse cx="31" cy="41.6" rx="1.9" ry="1.1" fill="#f2b8a0" opacity=".65" />
      </g>
      <!-- 周六：伸懒腰前肢前探 -->
      <path v-if="pose.extra === 'stretch'" d="M42 66 L28 79 M48 67 L36 81" stroke="#b5793f" stroke-width="2.6" stroke-linecap="round" fill="none" />
    </g>
  </svg>
</template>

<style scoped>
.fawn-illustration { display: block }
</style>
