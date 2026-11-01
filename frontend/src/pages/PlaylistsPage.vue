<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { request } from '../api/client'
import type { Playlist } from '../api/types'
import { useResource } from '../use-resource'
import { message } from '../session'
import { navigate } from '../router'
import LoadState from '../components/LoadState.vue'
const name = ref(''), busy = ref(false), feedback = ref('')
const { data, loading, error, load } = useResource(() => request<Playlist[]>('/api/v1/playlists/'))
onMounted(load)
async function create() {
  if (busy.value || !name.value.trim()) return
  busy.value = true; feedback.value = ''
  try { const list = await request<Playlist>('/api/v1/playlists/', { method: 'POST', body: JSON.stringify({ name: name.value.trim() }) }); navigate('/playlists/' + list.id) }
  catch (failure) { feedback.value = message(failure) } finally { busy.value = false }
}
</script>
<template><section class="content-card list-card"><p class="section-kicker">CURATED BY YOU</p><h2>为每种心情建一张歌单</h2><form class="inline-form" @submit.prevent="create"><input v-model="name" required maxlength="60" placeholder="新歌单名称" aria-label="新歌单名称" /><button class="primary-button" :disabled="busy || !name.trim()">{{ busy ? '创建中…' : '创建歌单' }}</button></form><p v-if="feedback" role="alert" class="error-text">{{ feedback }}</p><LoadState :loading="loading" :error="error" @retry="load" /><div v-if="data && !loading && !error" class="playlist-grid"><button v-for="list in data" :key="list.id" class="playlist-tile" @click="navigate('/playlists/' + list.id)"><span aria-hidden="true">♫</span><strong>{{ list.name }}</strong><small>打开歌单 →</small></button><p v-if="!data.length" class="empty-copy">还没有歌单，创建一个开始整理音乐。</p></div></section></template>
