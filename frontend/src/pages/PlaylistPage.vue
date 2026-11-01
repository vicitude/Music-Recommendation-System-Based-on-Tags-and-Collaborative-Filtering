<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { request } from '../api/client'
import type { PlaylistDetail } from '../api/types'
import { useResource } from '../use-resource'
import { message } from '../session'
import { currentPath, navigate } from '../router'
import LoadState from '../components/LoadState.vue'
import SongList from '../components/SongList.vue'
const id = Number(currentPath().split('/').pop())
const name = ref(''), busy = ref(false), feedback = ref(''), confirmDelete = ref(false)
const { data, loading, error, load } = useResource(async () => { const result = await request<PlaylistDetail>('/api/v1/playlists/' + id + '/'); name.value = result.name; return result })
onMounted(load)
async function mutate(remove = false) {
  if (busy.value || (!remove && !name.value.trim())) return
  busy.value = true; feedback.value = ''
  try { await request('/api/v1/playlists/' + id + '/', { method: remove ? 'DELETE' : 'PATCH', ...(remove ? {} : { body: JSON.stringify({ name: name.value.trim() }) }) }); if (remove) navigate('/playlists'); else { feedback.value = '名称已保存'; await load() } }
  catch (failure) { feedback.value = message(failure) } finally { busy.value = false }
}
</script>
<template><section class="content-card list-card"><button class="text-button" @click="navigate('/playlists')">← 我的歌单</button><LoadState :loading="loading" :error="error" @retry="load" /><template v-if="data && !loading && !error"><h2>{{ data.name }}</h2><form class="inline-form" @submit.prevent="mutate()"><input v-model="name" required maxlength="60" aria-label="歌单名称" /><button :disabled="busy || !name.trim()">保存名称</button><button type="button" class="danger-button" :disabled="busy" @click="confirmDelete = true">删除歌单</button></form><div v-if="confirmDelete" class="confirm-box" role="alert"><p>确认删除「{{ data.name }}」？只删除歌单，不删除歌曲或收藏。</p><button class="danger-button" :disabled="busy" @click="mutate(true)">确认删除</button><button :disabled="busy" @click="confirmDelete = false">取消</button></div><div class="section-heading"><p>{{ data.songs.length }} 首歌曲</p><button @click="navigate('/discover')">去发现页添加歌曲</button></div><SongList :songs="data.songs" :playlist-id="id" @changed="load" /><p v-if="!data.songs.length" class="empty-copy">这张歌单还是空的。在发现页或歌曲详情中选择「加入歌单」。</p></template><p v-if="feedback" role="status" class="inline-note">{{ feedback }}</p></section></template>
