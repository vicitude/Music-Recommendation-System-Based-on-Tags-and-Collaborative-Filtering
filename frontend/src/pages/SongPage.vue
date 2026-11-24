<script setup lang="ts">
import { onMounted, onUnmounted, ref } from 'vue'
import { request } from '../api/client'
import type { Song } from '../api/types'
import { currentPath, navigate } from '../router'
import { useResource } from '../use-resource'
import LoadState from '../components/LoadState.vue'
import SongList from '../components/SongList.vue'
import SongComments from '../components/SongComments.vue'
const id = Number(currentPath().split('/').pop())
const { data, loading, error, load } = useResource(() => request<Song>('/api/v1/songs/' + id + '/'))
onMounted(load)
const copying = ref(false), shareFeedback = ref(''), manualLink = ref('')
let disposed = false
onUnmounted(() => { disposed = true })
async function copySongLink() {
  if (disposed || copying.value || !data.value || loading.value || error.value) return
  const link = window.location.origin + window.location.pathname + '#/songs/' + data.value.id
  copying.value = true; shareFeedback.value = ''; manualLink.value = ''
  try {
    await navigator.clipboard.writeText(link)
    if (!disposed) shareFeedback.value = '已复制歌曲链接'
  } catch {
    if (!disposed) {
      manualLink.value = link
      shareFeedback.value = '无法自动复制，请选中下方链接并手动复制。'
    }
  } finally { if (!disposed) copying.value = false }
}
function safeLink(value: string) { try { const url = new URL(value); return ['http:', 'https:'].includes(url.protocol) ? url.href : undefined } catch { return undefined } }
</script>
<template><section class="content-card list-card"><button class="text-button" @click="navigate('/discover')">← 发现音乐</button><LoadState :loading="loading" :error="error" @retry="load" /><template v-if="data && !loading && !error"><p class="section-kicker">TRACK DETAILS</p><h2>{{ data.title }}</h2><SongList :songs="[data]" show-unfavorite /><div class="song-share"><button class="share-button" :disabled="copying" @click="copySongLink">{{ copying ? '复制中…' : '复制歌曲链接' }}</button><p class="share-warning">本机地址仅在当前电脑可打开；其他人访问需部署可访问地址</p><p v-if="shareFeedback" class="share-feedback" role="status">{{ shareFeedback }}</p><label v-if="manualLink" class="share-manual">歌曲链接（请手动复制）<input :value="manualLink" type="text" readonly @focus="($event.target as HTMLInputElement).select()" /></label></div><div class="license-info"><h3>来源与授权说明</h3><p>{{ data.attribution_text || '暂无署名说明' }}</p><p>{{ data.license_name || '暂无公开许可信息' }}</p><a v-if="safeLink(data.source_url)" :href="safeLink(data.source_url)" target="_blank" rel="noopener noreferrer">查看素材来源 ↗</a> <a v-if="safeLink(data.license_url)" :href="safeLink(data.license_url)" target="_blank" rel="noopener noreferrer">查看授权条款 ↗</a></div><SongComments :key="data.id" :song-id="data.id" /></template></section></template>
<style scoped>
.song-share { display: flex; flex-wrap: wrap; align-items: center; gap: 8px 12px; margin-top: 12px; min-width: 0; }
.share-button { display: inline-block; min-height: 44px; padding: 10px 16px; border-radius: 99px; color: #fff; background: #282633; font-size: 12px; }
.share-warning { flex: 1 1 280px; margin: 0; font-size: 13px; line-height: 1.5; }
.share-feedback { flex-basis: 100%; margin: 0; font-size: 13px; }
.share-manual { display: grid; gap: 4px; width: 100%; min-width: 0; font-size: 13px; }
.share-manual input { box-sizing: border-box; width: 100%; min-width: 0; }
</style>
