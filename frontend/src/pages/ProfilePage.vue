<script setup lang="ts">
import { computed, onUnmounted, ref, shallowRef, watch } from 'vue'
import { request } from '../api/client'
import type { HistoryPage } from '../api/types'
import { message, user } from '../session'
import { navigate } from '../router'
import LoadState from '../components/LoadState.vue'
import SongList from '../components/SongList.vue'

const page = ref(1), data = shallowRef<HistoryPage | null>(null), loading = ref(false), error = ref('')
const songs = computed(() => data.value?.items.map(item => item.song) ?? [])
const playedAt = computed(() => Object.fromEntries(data.value?.items.map(item => [item.song.id, item.last_played_at]) ?? []))
const dateFormat = new Intl.DateTimeFormat('zh-CN', { year: 'numeric', month: 'long', day: 'numeric', hour: '2-digit', minute: '2-digit', hour12: false })
let revision = 0
async function load() {
  const current = ++revision, ownerId = user.value?.id
  if (ownerId === undefined) return
  loading.value = true; error.value = ''
  try {
    const result = await request<HistoryPage>('/api/v1/me/history/?page=' + page.value)
    if (current === revision && user.value?.id === ownerId) data.value = result
  } catch (failure) {
    if (current === revision && user.value?.id === ownerId) error.value = message(failure)
  } finally { if (current === revision) loading.value = false }
}
watch(() => user.value?.id, () => {
  revision++; data.value = null; page.value = 1; error.value = ''; loading.value = false
  void load()
}, { immediate: true, flush: 'sync' })
onUnmounted(() => { revision++ })
function localDate(value: string) { return dateFormat.format(new Date(value)) }
function turn(delta: number) {
  if (loading.value || !data.value) return
  const next = page.value + delta
  if (next < 1 || next > Math.max(1, Math.ceil(data.value.total / data.value.page_size))) return
  page.value = next
  void load()
}
</script>
<template>
  <div class="profile-page">
    <section class="content-card profile-summary" aria-labelledby="profile-account">
      <div><p class="section-kicker">YOUR ACCOUNT</p><h2 id="profile-account">账号名：{{ user?.username }}</h2></div>
      <div class="actions"><button @click="navigate('/users/' + user?.id)">我的主页</button><button @click="navigate('/users/' + user?.id + '/following')">我的关注</button><button @click="navigate('/users/' + user?.id + '/followers')">粉丝</button><button @click="navigate('/favorites')">我的收藏</button><button @click="navigate('/onboarding')">兴趣设置</button></div>
    </section>
    <section class="content-card list-card" aria-labelledby="profile-history" :aria-busy="loading">
      <div class="section-heading"><h2 id="profile-history">最近听歌</h2><button :disabled="loading" @click="load">刷新最近听歌</button></div>
      <LoadState :loading="loading" :error="error" @retry="load" />
      <template v-if="data && !loading && !error">
        <SongList :songs="songs" :index-offset="(data.page - 1) * data.page_size">
          <template #metadata="{ song }"><p class="history-date">最近播放：<time :datetime="playedAt[song.id]">{{ localDate(playedAt[song.id]) }}</time></p></template>
        </SongList>
        <p v-if="!data.items.length" class="empty-copy">还没有最近听歌记录。<button @click="navigate('/discover')">去发现音乐</button></p>
      </template>
      <nav v-if="data && data.total" class="pagination" aria-label="最近听歌分页">
        <button :disabled="loading || page <= 1" @click="turn(-1)">上一页</button>
        <span role="status">共 {{ data.total }} 首 · 第 {{ page }} 页</span>
        <button :disabled="loading || page * data.page_size >= data.total" @click="turn(1)">下一页</button>
      </nav>
    </section>
  </div>
</template>
