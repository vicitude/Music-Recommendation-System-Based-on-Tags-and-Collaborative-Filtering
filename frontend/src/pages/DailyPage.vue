<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { ApiError, request } from '../api/client'
import type { Daily, Song, Tag } from '../api/types'
import { useResource } from '../use-resource'
import { navigate } from '../router'
import { message } from '../session'
import LoadState from '../components/LoadState.vue'
import SongList from '../components/SongList.vue'
const refreshing = ref(false), feedback = ref(''), now = ref(Date.now()), retryAt = ref(0), sceneId = ref('')
const scenes = ref<Tag[]>([])
const sceneQuery = computed(() => sceneId.value ? '?scene_id=' + sceneId.value : '')
const { data, loading, error, load } = useResource(async () => hydrate(await request<Daily>('/api/v1/recommendations/daily/' + sceneQuery.value)))
async function hydrate(daily: Daily) {
  const tracks = await Promise.all(daily.items.map(async item => {
    try { return await request<Song>('/api/v1/songs/' + item.song_id + '/') }
    catch (failure) { if (failure instanceof ApiError && failure.body.error_code === 'NOT_FOUND') return null; throw failure }
  }))
  return { daily, tracks: tracks.filter((song): song is Song => song !== null) }
}
const remaining = computed(() => Math.max(0, Math.ceil((Math.max(retryAt.value, Date.parse(data.value?.daily.next_refresh_at || '') || 0) - now.value) / 1000)))
const explanations = computed(() => Object.fromEntries((data.value?.daily.items || []).map(item => [item.song_id, item.explanation])))
const ranks = computed(() => Object.fromEntries((data.value?.daily.items || []).map(item => [item.song_id, item.rank])))
let timer: ReturnType<typeof setInterval>
let active = true
onMounted(() => { void load(); timer = setInterval(() => { now.value = Date.now() }, 1000) })
onMounted(async () => { try { scenes.value = (await request<Tag[]>('/api/v1/tags/')).filter(tag => tag.kind === 'SCENE') } catch { scenes.value = [] } })
onUnmounted(() => { active = false; clearInterval(timer) })
async function refresh() {
  if (refreshing.value || loading.value || remaining.value) return
  refreshing.value = true; feedback.value = ''
  try {
    const daily = await request<Daily>('/api/v1/recommendations/daily/refresh/' + sceneQuery.value, { method: 'POST' })
    const result = await hydrate(daily)
    if (active) { data.value = result; now.value = Date.now() }
  } catch (failure) {
    if (active) { feedback.value = message(failure); if (failure instanceof ApiError && failure.retryAfter) retryAt.value = Date.now() + failure.retryAfter * 1000 }
  } finally { if (active) refreshing.value = false }
}
</script>
<template><section class="hero-card daily-hero"><div><p class="hero-kicker">TODAY'S MIX · 标签 × 行为</p><h2>今天，听见更合拍的声音。</h2><p class="hero-copy">从兴趣标签出发，结合相似用户的真实偏好。每首推荐都附上来自系统的推荐理由。</p></div><button class="primary-button" @click="navigate('/onboarding')">调整兴趣标签</button></section><section class="content-card list-card daily-results"><div class="section-heading"><div><h2>为你精选</h2><p v-if="data" class="muted">{{ data.daily.day }} · 第 {{ data.daily.revision }} 版</p></div><button :disabled="loading || refreshing || remaining > 0" @click="refresh">{{ refreshing ? '更新中…' : remaining ? remaining + ' 秒后可刷新' : '刷新推荐' }}</button></div><div class="daily-scene"><label for="daily-scene">想听什么场景</label><select id="daily-scene" v-model="sceneId" @change="load"><option value="">跟随时段自动选择</option><option v-for="scene in scenes" :key="scene.id" :value="String(scene.id)">{{ scene.name }}</option></select><span v-if="data?.daily.scene_name" class="muted">当前：{{ data.daily.scene_name }}（{{ data.daily.scene_source === 'USER' ? '手动选择' : '时段推荐' }}）</span></div><details class="recommendation-help"><summary>推荐如何产生？</summary><p class="muted">每次最多推荐10首，候选不足时按实际数量显示。场景会根据你的选择或上海时间调整三路融合权重；没有场景时保持原有推荐逻辑。</p></details><p v-if="feedback" role="alert" class="error-text">{{ feedback }}</p><LoadState :loading="loading" :error="error" @retry="load" /><template v-if="data && !loading && !error"><SongList :songs="data.tracks" :explanations="explanations" :ranks="ranks" /><div v-if="!data.tracks.length" class="empty-copy"><p>{{ data.daily.empty_reason === 'FILTERED_OUT' ? '这一版推荐已被收藏或可用性规则过滤，可稍后刷新或去发现页探索。' : data.daily.empty_reason === 'NO_ELIGIBLE_SONGS' ? '暂无符合条件的可推荐歌曲，需先准备已核验授权并发布的曲库。' : '推荐歌曲当前不可用，请重试或刷新推荐。' }}</p><button @click="navigate('/discover')">去发现音乐</button></div></template></section></template>
