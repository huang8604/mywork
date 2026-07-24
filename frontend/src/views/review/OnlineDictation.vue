<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useDictationPlayer } from '@/composables/useDictationPlayer'
import { practiceItemAudioUrl } from '@/api/practiceSessions'
import type { DictationAccent, DictationSettings, PracticeSession } from '@/types/domain'

const props = defineProps<{ session: PracticeSession; sessions: PracticeSession[] }>()
const emit = defineEmits<{ select: [sessionId: number]; back: [] }>()

const settings = ref<DictationSettings>({
  intervalSec: 5,
  autoAdvance: true,
  accent: 'us',
  rate: 1,
  repeat: 1,
})

const texts = () => props.session.items?.map(i => i.word.en_word) ?? []
const audioUrls = () => props.session.items?.map(i => practiceItemAudioUrl(props.session.session_id, i.item_id)) ?? []
const player = useDictationPlayer({ texts, audioUrls })

const draft = ref('')
const startedAt = ref<number | null>(null)
const finishedAt = ref<number | null>(null)

const total = computed(() => props.session.items?.length ?? 0)
const accentLabel: Record<DictationAccent, string> = { us: '美音', uk: '英音', system: '系统默认' }

// 切换复习表：停播放、回到设置态（保留用户已调好的设置）。
watch(() => props.session?.session_id, () => {
  player.stop()
  draft.value = ''
})
// 换词：清空草稿（草稿不判对错、不提交）。
watch(() => player.index.value, () => { draft.value = '' })
// 引擎跑完：记一个结束时刻用于算用时。
watch(() => player.phase.value, phase => {
  if (phase === 'finished') finishedAt.value = Date.now()
})

function begin() {
  startedAt.value = Date.now()
  finishedAt.value = null
  player.start(settings.value)
}
function onEnter() {
  // 草稿框里按回车 = 手动「下一个并播放」（自动模式下也会取消等待中的间隔定时器）。
  if (player.phase.value === 'running') player.nextAndPlay()
}
function formatElapsed(): string {
  if (!startedAt.value) return '—'
  const end = finishedAt.value ?? Date.now()
  const sec = Math.max(0, Math.round((end - startedAt.value) / 1000))
  const m = Math.floor(sec / 60)
  const s = sec % 60
  return m > 0 ? `${m} 分 ${s} 秒` : `${s} 秒`
}
const speakingHint = computed(() => {
  if (player.isSpeaking.value) return '正在播放…'
  if (!settings.value.autoAdvance) return '点「下一个并播放」继续，或「重播」再听一遍'
  return `${settings.value.intervalSec} 秒后自动播放下一词（可点「下一个并播放」立即继续）`
})
</script>

<template>
  <section class="dictation panel">
    <header class="dict-head">
      <div>
        <p class="eyebrow">ONLINE DICTATION · 在线默写</p>
        <h2>{{ session.title?.trim() || `复习表 #${session.session_id}` }}</h2>
        <p class="muted">听音默写 · 不计入结果，需手动回录 · 共 {{ total }} 词</p>
      </div>
      <div class="head-right">
        <el-select :model-value="session.session_id" size="small" aria-label="切换复习表" @change="(v: number) => emit('select', v)">
          <el-option v-for="s in sessions" :key="s.session_id" :value="s.session_id" :label="s.title?.trim() || `复习表 #${s.session_id}`" />
        </el-select>
        <el-button size="small" @click="emit('back')">返回卡片</el-button>
      </div>
    </header>

    <!-- 不支持 speechSynthesis -->
    <div v-if="!player.supported" class="unsupported">
      当前浏览器既不支持音频播放，也不支持语音合成（speechSynthesis），无法使用在线默写。请换用 Chrome / Edge / Safari。
    </div>

    <!-- 设置态 -->
    <div v-else-if="player.phase.value === 'idle'" class="setup">
      <div class="setting-grid">
        <label class="setting">
          <span>自动播放下一词</span>
          <el-switch v-model="settings.autoAdvance" />
        </label>
        <label class="setting">
          <span>间隔 · {{ settings.intervalSec }} 秒</span>
          <el-slider v-model="settings.intervalSec" :min="2" :max="30" :step="1" :disabled="!settings.autoAdvance" />
        </label>
        <label class="setting">
          <span>每词播放次数 · {{ settings.repeat }} 次</span>
          <el-slider v-model="settings.repeat" :min="1" :max="3" :step="1" />
        </label>
        <label class="setting">
          <span>语速 · {{ settings.rate.toFixed(1) }}</span>
          <el-slider v-model="settings.rate" :min="0.7" :max="1.2" :step="0.1" />
        </label>
        <label class="setting">
          <span>口音</span>
          <el-radio-group v-model="settings.accent" aria-label="口音">
            <el-radio-button value="us">美音</el-radio-button>
            <el-radio-button value="uk">英音</el-radio-button>
            <el-radio-button value="system">系统默认</el-radio-button>
          </el-radio-group>
        </label>
      </div>
      <p v-if="player.voiceWarning.value" class="warning">{{ player.voiceWarning.value }}</p>
      <p class="muted hint">点击「开始默写」后由你启动第一段语音；英文会隐藏，只留题号、草稿框与播放控制。</p>
      <el-button type="primary" size="large" :disabled="!total" @click="begin">开始默写</el-button>
    </div>

    <!-- 运行态 -->
    <div v-else-if="player.phase.value === 'running'" class="runner">
      <div class="runner-top">
        <span class="qnum">{{ player.index.value + 1 }} / {{ player.total.value || total }}</span>
        <el-progress :percentage="player.total.value ? Math.round(((player.index.value) / player.total.value) * 100) : 0" :show-text="false" />
      </div>
      <div class="draft-wrap">
        <span class="card-label">听音默写（草稿 · 不判对错）</span>
        <el-input
          v-model="draft"
          placeholder="听到什么就写什么，回车 = 下一个并播放"
          size="large"
          autocomplete="off"
          autocapitalize="off"
          spellcheck="false"
          @keyup.enter="onEnter"
        />
      </div>
      <p class="speaking-hint" :class="{ on: player.isSpeaking.value }" aria-live="polite">{{ speakingHint }}</p>
      <p v-if="player.voiceWarning.value" class="warning small">{{ player.voiceWarning.value }}</p>
      <div class="runner-controls">
        <el-button size="large" @click="player.replay()">重播</el-button>
        <el-button size="large" @click="player.skip()">跳过</el-button>
        <el-button type="primary" size="large" @click="player.nextAndPlay()">下一个并播放</el-button>
      </div>
      <div class="runner-meta">
        <span>已听 {{ player.counts.value.played }} · 跳过 {{ player.counts.value.skipped }}</span>
        <span>间隔 {{ settings.intervalSec }}s · 语速 {{ settings.rate.toFixed(1) }} · {{ accentLabel[settings.accent] }} · {{ settings.repeat }} 次</span>
        <el-button link type="primary" @click="player.stop()">结束</el-button>
      </div>
    </div>

    <!-- 完成态 -->
    <div v-else class="finished">
      <p class="eyebrow">DONE</p>
      <h2>本轮默写完成</h2>
      <div class="finish-counts">
        <span><strong>{{ player.counts.value.played }}</strong> 已听</span>
        <span><strong>{{ player.counts.value.skipped }}</strong> 跳过</span>
        <span><strong>{{ total }}</strong> 总词数</span>
        <span><strong>{{ formatElapsed() }}</strong> 用时</span>
      </div>
      <p class="muted">听写不计入结果。请到「在线卡片」或「结果回录」手动记录本轮掌握情况。</p>
      <div class="finish-actions">
        <el-button type="primary" @click="begin">再来一次</el-button>
        <el-button @click="player.stop()">返回设置</el-button>
        <el-button @click="emit('back')">返回卡片</el-button>
      </div>
    </div>
  </section>
</template>

<style scoped>
.dictation { margin-top: 14px; }
.dict-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; flex-wrap: wrap; }
.dict-head h2 { margin: 2px 0; font: 700 1.4rem Georgia, serif; }
.head-right { display: flex; gap: 8px; align-items: center; }
.muted { color: var(--muted); font-size: .85rem; margin: 4px 0 0; }
.eyebrow { color: var(--muted); font-size: .68rem; letter-spacing: .14em; text-transform: uppercase; margin: 0; }
.unsupported { margin-top: 18px; padding: 16px; border-radius: 10px; background: #fff0ef; color: var(--red); border: 1px solid var(--red); }
.warning { color: #987226; background: #fff7df; border: 1px solid #e6cf8e; padding: 6px 10px; border-radius: 8px; font-size: .82rem; margin: 10px 0; }
.warning.small { padding: 4px 8px; font-size: .76rem; display: inline-block; }
.hint { margin: 12px 0; line-height: 1.7; }

.setting-grid { display: grid; gap: 18px 24px; grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); margin: 18px 0; }
.setting { display: flex; flex-direction: column; gap: 8px; font-size: .85rem; }
.setting > span { color: var(--muted); font-weight: 600; }
.setup { text-align: center; }
.setup .el-button { margin-top: 8px; }

.runner { display: flex; flex-direction: column; gap: 14px; }
.runner-top { display: flex; align-items: center; gap: 14px; }
.qnum { font-weight: 800; color: var(--green-800); white-space: nowrap; }
.runner-top .el-progress { flex: 1; }
.draft-wrap { display: flex; flex-direction: column; gap: 6px; }
.card-label { color: var(--muted); font-size: .72rem; letter-spacing: .1em; text-transform: uppercase; }
.speaking-hint { text-align: center; color: var(--muted); margin: 4px 0; min-height: 1.2em; }
.speaking-hint.on { color: var(--green-800); font-weight: 700; }
.runner-controls { display: flex; justify-content: center; gap: 12px; flex-wrap: wrap; }
.runner-meta { display: flex; justify-content: space-between; align-items: center; gap: 12px; flex-wrap: wrap; color: var(--muted); font-size: .78rem; padding-top: 8px; border-top: 1px dashed var(--line); }

.finished { text-align: center; padding: 12px 0; }
.finished h2 { font: 700 1.6rem Georgia, serif; margin: 4px 0 14px; }
.finish-counts { display: flex; justify-content: center; gap: 22px; flex-wrap: wrap; margin-bottom: 14px; }
.finish-counts span { color: var(--muted); font-size: .9rem; }
.finish-counts strong { display: block; font-size: 1.6rem; color: var(--ink); font-family: Georgia, serif; }
.finish-actions { display: flex; justify-content: center; gap: 10px; flex-wrap: wrap; }

@media (max-width: 639px) {
  .dict-head { flex-direction: column; }
  .head-right { width: 100%; }
  .head-right .el-select { flex: 1; }
}
</style>
