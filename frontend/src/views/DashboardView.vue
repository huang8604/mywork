<script setup lang="ts">
import { onMounted, ref } from 'vue'
import AsyncState from '@/components/AsyncState.vue'
import { getStatsSummary } from '@/api/stats'
import { listSessions } from '@/api/practiceSessions'
import { listWords } from '@/api/words'
import { useAsyncState } from '@/composables/useAsyncState'
import type { PracticeSession, StatsSummary } from '@/types/domain'

const state=useAsyncState<{stats:StatsSummary;wordCount:number;sessions:PracticeSession[]}>(); const now=ref(new Date())
const dateText=()=>new Intl.DateTimeFormat('zh-CN',{month:'long',day:'numeric',weekday:'long'}).format(now.value)
async function load(){await state.run(async signal=>{const [stats,words,sessions]=await Promise.all([getStatsSummary(signal),listWords({page:1,size:1},signal),listSessions(1,4,signal)]);return{stats,wordCount:Number(words.meta.total||0),sessions:sessions.data}}).catch(()=>{})}
onMounted(load)
</script>
<template>
  <section class="page"><div class="page-heading"><div><p class="eyebrow">{{ dateText() }}</p><h2>欢迎回来，今天也拾起几个词。</h2></div><el-button type="primary" size="large" @click="$router.push('/daily/generate')">生成今日复习表</el-button></div>
    <AsyncState :phase="state.phase.value" :error="state.error.value" @retry="load">
      <template v-if="state.data.value"><div class="stats-grid">
        <article class="stat-card primary"><small>累计单词</small><strong>{{ state.data.value.wordCount }}</strong><span>词库持续生长中</span></article>
        <article class="stat-card"><small>总复习次数</small><strong>{{ state.data.value.stats.total_attempts }}</strong><span>跳过 {{ state.data.value.stats.skipped_count }} 次</span></article>
        <article class="stat-card"><small>有效正确率</small><strong>{{ state.data.value.stats.accuracy===null?'—':Math.round(state.data.value.stats.accuracy*100)+'%' }}</strong><span>认识 {{ state.data.value.stats.known_count }} 次</span></article>
        <article class="stat-card"><small>今日到期</small><strong>{{ state.data.value.stats.due_words }}</strong><span>建议优先复习</span></article>
      </div>
      <div class="dashboard-grid"><article class="panel"><div class="section-title"><div><p class="eyebrow">QUICK START</p><h2>开始一次复习</h2></div></div><p class="muted">在线复习适合临时练习；平时建议生成复习表，在线下完成后回来回录结果。</p><div class="button-row"><el-button type="primary" @click="$router.push('/review')">在线卡片复习</el-button><el-button @click="$router.push('/words')">管理词库</el-button></div></article>
        <article class="panel"><div class="section-title"><div><p class="eyebrow">RECENT SHEETS</p><h2>最近复习表</h2></div><el-button link @click="$router.push('/daily/generate')">查看全部</el-button></div><ul v-if="state.data.value.sessions.length" class="session-list"><li v-for="session in state.data.value.sessions" :key="session.session_id"><RouterLink :to="`/daily/sessions/${session.session_id}`"><span>#{{ session.session_id }} · {{ new Date(session.generated_at).toLocaleDateString('zh-CN') }}</span><span v-if="session.created_by_actor_type==='api_client'" class="source-pill">外部 Skill</span><small>{{ Object.values(session.actual_counts).reduce((a,b)=>a+b,0) }} 词</small></RouterLink></li></ul><p v-else class="muted">还没有复习表。</p></article>
      </div></template>
    </AsyncState>
  </section>
</template>
<style scoped>.stats-grid{display:grid;grid-template-columns:repeat(4,1fr);gap:14px}.stat-card{display:grid;gap:7px;padding:20px;border:1px solid var(--line);background:var(--paper);border-radius:17px}.stat-card.primary{background:var(--green-950);color:#fff}.stat-card small,.stat-card span{color:var(--muted)}.stat-card.primary small,.stat-card.primary span{color:#bfd1c8}.stat-card strong{font:700 2.25rem Georgia,serif}.dashboard-grid{display:grid;grid-template-columns:1fr 1.25fr;gap:18px}.section-title{display:flex;align-items:flex-start;justify-content:space-between}.session-list{list-style:none;margin:0;padding:0;display:grid}.session-list li+li{border-top:1px solid var(--line)}.session-list a{min-height:56px;display:grid;grid-template-columns:1fr auto auto;align-items:center;gap:10px;text-decoration:none;color:var(--ink)}.session-list small{color:var(--muted)}@media(max-width:1023px){.stats-grid{grid-template-columns:repeat(2,1fr)}.dashboard-grid{grid-template-columns:1fr}}@media(max-width:639px){.stats-grid{grid-template-columns:1fr 1fr;gap:10px}.stat-card{padding:15px}.stat-card strong{font-size:1.75rem}.stat-card span{font-size:.78rem}}</style>
