<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import AsyncState from '@/components/AsyncState.vue'
import { getContributions, getOwnContributions, getOwnStatsSummary, getStatsSummary } from '@/api/stats'
import { listSessions } from '@/api/practiceSessions'
import { listWords } from '@/api/words'
import { useAsyncState } from '@/composables/useAsyncState'
import type { ContributionDay, ContributionsSummary, PracticeSession, StatsSummary } from '@/types/domain'
import { useAuthStore } from '@/stores/auth'

const state = useAsyncState<{ stats: StatsSummary; contributions: ContributionsSummary; wordCount: number; sessions: PracticeSession[] }>()
const auth = useAuthStore()
const isAdmin = computed(() => auth.role === 'admin')
const now = ref(new Date())
const activeDay = ref<ContributionDay | null>(null)
const dateText = () => new Intl.DateTimeFormat('zh-CN', { month: 'long', day: 'numeric', weekday: 'long' }).format(now.value)
const dateParts = (date: string) => date.split('-').map(Number) as [number, number, number]
const mondayOffset = (date: string) => {
  const [year, month, day] = dateParts(date)
  return (new Date(Date.UTC(year, month - 1, day)).getUTCDay() + 6) % 7
}
const contributionCells = computed<Array<ContributionDay | null>>(() => {
  const days = state.data.value?.contributions.days || []
  return days.length ? [...Array<null>(mondayOffset(days[0].date)).fill(null), ...days] : []
})
const weekCount = computed(() => Math.ceil(contributionCells.value.length / 7))
const monthLabels = computed(() => {
  const labels: Array<{ week: number; label: string }> = []
  let previous = ''
  contributionCells.value.forEach((day, index) => {
    if (!day) return
    const month = day.date.slice(0, 7)
    if (month === previous) return
    previous = month
    const [, value] = dateParts(day.date)
    labels.push({ week: Math.floor(index / 7) + 1, label: `${value}月` })
  })
  return labels
})
const activeDays = computed(() => state.data.value?.contributions.days.filter(day => day.count > 0).length ?? 0)
const bestDay = computed(() => state.data.value?.contributions.days.reduce<ContributionDay | null>((best, day) => !best || day.count > best.count ? day : best, null) ?? null)
const heatLevel = (count: number) => count === 0 ? 0 : count <= 2 ? 1 : count <= 5 ? 2 : count <= 9 ? 3 : 4
const contributionTitle = (day: ContributionDay) => `${day.date}：复习 ${day.count} 次（认识 ${day.known}，不认识 ${day.unknown}，跳过 ${day.skipped}）`
const prettyDay = (day: ContributionDay) => new Intl.DateTimeFormat('zh-CN', { month: 'long', day: 'numeric', weekday: 'short', timeZone: 'UTC' }).format(new Date(`${day.date}T00:00:00Z`))
async function load() {
  const loaded = await state.run(async signal => {
    if (isAdmin.value) {
      const [stats, contributions, words, sessions] = await Promise.all([getStatsSummary(signal), getContributions(signal), listWords({ page: 1, size: 1 }, signal), listSessions(1, 4, signal)])
      return { stats, contributions, wordCount: Number(words.meta.total || 0), sessions: sessions.data }
    }
    const [stats, contributions] = await Promise.all([getOwnStatsSummary(signal), getOwnContributions(signal)])
    return { stats, contributions, wordCount: stats.reviewed_words, sessions: [] }
  }).catch(() => undefined)
  if (loaded) activeDay.value = [...loaded.contributions.days].reverse().find(day => day.count > 0) ?? loaded.contributions.days.at(-1) ?? null
}
onMounted(load)
</script>

<template>
  <section class="page">
    <div class="page-heading"><div><p class="eyebrow">{{ dateText() }}</p><h2>{{ isAdmin ? '欢迎回来，今天也拾起几个词。' : '这是你的学习概览。' }}</h2></div><el-button v-if="isAdmin" type="primary" size="large" @click="$router.push('/daily/generate')">生成今日复习表</el-button></div>
    <AsyncState :phase="state.phase.value" :error="state.error.value" @retry="load">
      <template v-if="state.data.value">
        <article class="panel contribution-panel">
          <div class="contribution-head">
            <div><p class="eyebrow">365 DAY ACTIVITY</p><h2>一年背诵记录</h2><p class="muted">把每次复习积累成一片自己的绿色。</p></div>
            <div class="activity-facts" aria-label="年度背诵摘要"><span><strong>{{ state.data.value.contributions.total }}</strong><small>总复习</small></span><span><strong>{{ activeDays }}</strong><small>活跃天</small></span><span><strong>{{ bestDay?.count ?? 0 }}</strong><small>单日峰值</small></span></div>
          </div>
          <div class="heatmap-scroll" tabindex="0" aria-label="可横向滚动查看一年背诵记录">
            <div class="heatmap" :style="{ '--weeks': weekCount }">
              <div class="month-spacer" aria-hidden="true"></div>
              <div class="month-grid" aria-hidden="true"><span v-for="month in monthLabels" :key="`${month.week}-${month.label}`" :style="{ gridColumn: month.week }">{{ month.label }}</span></div>
              <div class="weekday-labels" aria-hidden="true"><span>一</span><span></span><span>三</span><span></span><span>五</span><span></span><span>日</span></div>
              <div class="contribution-grid" role="grid" aria-label="最近一年每日背诵情况">
                <template v-for="(day, index) in contributionCells" :key="day?.date || `blank-${index}`">
                  <button v-if="day" type="button" class="contribution-day" :class="[`level-${heatLevel(day.count)}`, { selected: activeDay?.date === day.date }]" :title="contributionTitle(day)" :aria-label="contributionTitle(day)" role="gridcell" @mouseenter="activeDay = day" @focus="activeDay = day" @click="activeDay = day"></button>
                  <span v-else class="contribution-day placeholder" aria-hidden="true"></span>
                </template>
              </div>
            </div>
          </div>
          <div class="contribution-footer">
            <div v-if="activeDay" class="day-detail" aria-live="polite"><span class="detail-dot" :class="`level-${heatLevel(activeDay.count)}`"></span><strong>{{ prettyDay(activeDay) }}</strong><span>复习 {{ activeDay.count }} 次</span><small>认识 {{ activeDay.known }} · 不认识 {{ activeDay.unknown }} · 跳过 {{ activeDay.skipped }}</small></div>
            <div class="heat-legend" aria-label="复习次数颜色图例"><small>少</small><i v-for="level in [0, 1, 2, 3, 4]" :key="level" :class="`level-${level}`"></i><small>多</small></div>
          </div>
        </article>
        <div class="stats-grid">
          <article class="stat-card primary"><small>{{ isAdmin ? '累计单词' : '已复习单词' }}</small><strong>{{ state.data.value.wordCount }}</strong><span>{{ isAdmin ? '词库持续生长中' : '只统计你的复习记录' }}</span></article>
          <article class="stat-card"><small>总复习次数</small><strong>{{ state.data.value.stats.total_attempts }}</strong><span>跳过 {{ state.data.value.stats.skipped_count }} 次</span></article>
          <article class="stat-card"><small>有效正确率</small><strong>{{ state.data.value.stats.accuracy === null ? '—' : Math.round(state.data.value.stats.accuracy * 100) + '%' }}</strong><span>认识 {{ state.data.value.stats.known_count }} 次</span></article>
          <article class="stat-card"><small>今日到期</small><strong>{{ state.data.value.stats.due_words }}</strong><span>建议优先复习</span></article>
        </div>
        <div class="dashboard-grid">
          <article class="panel"><div class="section-title"><div><p class="eyebrow">QUICK START</p><h2>开始一次复习</h2></div></div><p class="muted">{{ isAdmin ? '在线复习适合临时练习；平时建议生成复习表，在线下完成后回来回录结果。' : '进入在线复习，使用分配给你的进行中复习表。' }}</p><div class="button-row"><el-button type="primary" @click="$router.push('/review')">在线卡片复习</el-button><el-button v-if="isAdmin" @click="$router.push('/words')">管理词库</el-button></div></article>
          <article v-if="isAdmin" class="panel"><div class="section-title"><div><p class="eyebrow">RECENT SHEETS</p><h2>最近复习表</h2></div><el-button link @click="$router.push('/daily/generate')">查看全部</el-button></div><ul v-if="state.data.value.sessions.length" class="session-list"><li v-for="session in state.data.value.sessions" :key="session.session_id"><RouterLink :to="`/daily/sessions/${session.session_id}`"><span>#{{ session.session_id }} · {{ new Date(session.generated_at).toLocaleDateString('zh-CN') }}</span><span v-if="session.created_by_actor_type === 'api_client'" class="source-pill">外部 Skill</span><small>{{ Object.values(session.actual_counts).reduce((a, b) => a + b, 0) }} 词</small></RouterLink></li></ul><p v-else class="muted">还没有复习表。</p></article>
        </div>
      </template>
    </AsyncState>
  </section>
</template>

<style scoped>
.contribution-panel{display:grid;gap:18px;overflow:hidden;background:linear-gradient(145deg,#fff 0%,#fbfdfb 58%,#f1f8f4 100%)}.contribution-panel h2,.contribution-panel p{margin-bottom:0}.contribution-head{display:flex;align-items:flex-start;justify-content:space-between;gap:22px}.activity-facts{display:flex;gap:8px}.activity-facts span{min-width:76px;display:grid;gap:2px;padding:10px 12px;border:1px solid rgba(23,75,52,.12);border-radius:12px;background:rgba(255,255,255,.78);text-align:center}.activity-facts strong{font:700 1.25rem Georgia,serif;color:var(--green-800)}.activity-facts small{font-size:.7rem;color:var(--muted)}.heatmap-scroll{overflow-x:auto;overscroll-behavior-inline:contain;padding:2px 2px 8px;scrollbar-width:thin;outline:none}.heatmap-scroll:focus-visible{border-radius:8px;box-shadow:0 0 0 3px var(--green-100)}.heatmap{--cell:13px;--gap:3px;display:grid;grid-template-columns:22px max-content;grid-template-rows:18px auto;gap:5px 7px;width:max-content;min-width:100%}.month-grid{display:grid;grid-template-columns:repeat(var(--weeks),var(--cell));gap:var(--gap);height:18px;color:var(--muted);font-size:.68rem}.month-grid span{white-space:nowrap}.weekday-labels{display:grid;grid-template-rows:repeat(7,var(--cell));gap:var(--gap);color:var(--muted);font-size:.62rem;line-height:var(--cell);text-align:center}.contribution-grid{display:grid;grid-template-rows:repeat(7,var(--cell));grid-auto-flow:column;grid-auto-columns:var(--cell);gap:var(--gap);width:max-content}.contribution-day{box-sizing:border-box;width:var(--cell);height:var(--cell);padding:0;border:0;border-radius:3px;background:#e7ece9;box-shadow:inset 0 0 0 1px rgba(23,75,52,.04);transition:transform .16s ease,box-shadow .16s ease,filter .16s ease;cursor:pointer}.contribution-day:hover,.contribution-day:focus-visible,.contribution-day.selected{position:relative;z-index:2;transform:scale(1.34);box-shadow:0 2px 8px rgba(23,75,52,.28),inset 0 0 0 1px rgba(255,255,255,.5);filter:saturate(1.08)}.contribution-day:focus-visible{outline:2px solid #174b34;outline-offset:2px}.contribution-day.placeholder{visibility:hidden}.level-0{background:#e7ece9!important}.level-1{background:#b9d8c5!important}.level-2{background:#73ad8a!important}.level-3{background:#3f805e!important}.level-4{background:#174b34!important}.contribution-footer{min-height:35px;display:flex;align-items:center;justify-content:space-between;gap:16px;padding-top:12px;border-top:1px solid rgba(23,75,52,.1)}.day-detail{display:flex;align-items:center;gap:9px;min-width:0;color:var(--ink);font-size:.82rem}.day-detail>span:not(.detail-dot),.day-detail small{color:var(--muted)}.detail-dot{flex:0 0 auto;width:10px;height:10px;border-radius:3px}.heat-legend{display:flex;align-items:center;gap:4px;flex:0 0 auto}.heat-legend i{display:block;width:12px;height:12px;border-radius:3px}.heat-legend small{color:var(--muted)}.stats-grid{display:grid;grid-template-columns:repeat(4,1fr);gap:14px}.stat-card{display:grid;gap:7px;padding:20px;border:1px solid var(--line);background:var(--paper);border-radius:17px}.stat-card.primary{background:var(--green-950);color:#fff}.stat-card small,.stat-card span{color:var(--muted)}.stat-card.primary small,.stat-card.primary span{color:#bfd1c8}.stat-card strong{font:700 2.25rem Georgia,serif}.dashboard-grid{display:grid;grid-template-columns:1fr 1.25fr;gap:18px}.section-title{display:flex;align-items:flex-start;justify-content:space-between;gap:16px}.session-list{list-style:none;margin:0;padding:0;display:grid}.session-list li+li{border-top:1px solid var(--line)}.session-list a{min-height:56px;display:grid;grid-template-columns:1fr auto auto;align-items:center;gap:10px;text-decoration:none;color:var(--ink)}.session-list small{color:var(--muted)}
@media(max-width:1023px){.stats-grid{grid-template-columns:repeat(2,1fr)}.dashboard-grid{grid-template-columns:1fr}}
@media(max-width:639px){.contribution-head{display:grid}.activity-facts{width:100%}.activity-facts span{flex:1;min-width:0;padding:8px}.heatmap{--cell:12px}.contribution-footer{align-items:flex-start}.day-detail{display:grid;grid-template-columns:auto 1fr}.day-detail small{grid-column:2}.heat-legend{align-self:center}.stats-grid{grid-template-columns:1fr 1fr;gap:10px}.stat-card{padding:15px}.stat-card strong{font-size:1.75rem}.stat-card span{font-size:.78rem}}
@media(prefers-reduced-motion:reduce){.contribution-day{transition:none}}
</style>
