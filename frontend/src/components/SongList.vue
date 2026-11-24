<script setup lang="ts">
import { inject, onUnmounted, ref, watch } from 'vue'
import { request } from '../api/client'
import type { Playlist, Song, SongPage } from '../api/types'
import { playerKey } from '../player-context'
import { message, user } from '../session'
import { navigate } from '../router'
const props = defineProps<{ songs: Song[]; indexOffset?: number; favoriteMode?: boolean; showUnfavorite?: boolean; playlistId?: number; explanations?: Record<number, string>; ranks?: Record<number, number> }>()
const emit = defineEmits<{ changed: [] }>()
const player = inject(playerKey)
const busy = ref(false), feedback = ref(''), lists = ref<Playlist[]>([]), selectedSong = ref<Song | null>(null), selectedList = ref('')
const favoriteIds = ref<Set<number>>(new Set()), favoritesReady = ref(false), favoritesError = ref(''), ratings = ref<Record<number, number | null>>({})
let generation = 0
async function loadFavorites() {
  const current = ++generation
  favoritesReady.value = false; favoritesError.value = ''; favoriteIds.value = new Set()
  if (!user.value) { favoritesReady.value = true; return }
  try {
    const ids = new Set<number>()
    let page = 1
    while (true) {
      const result = await request<SongPage>('/api/v1/favorites/?page=' + page + '&page_size=100')
      if (current !== generation) return
      result.results.forEach(song => ids.add(song.id))
      if (page * result.page_size >= result.count) break
      page += 1
    }
    favoriteIds.value = ids; favoritesReady.value = true
  } catch (failure) { if (current === generation) favoritesError.value = message(failure) }
}
watch(() => user.value?.id, loadFavorites, { immediate: true })
onUnmounted(() => { generation += 1 })
function isFavorite(song: Song) { return props.favoriteMode || favoriteIds.value.has(song.id) }
function rating(song: Song) { return ratings.value[song.id] ?? song.current_rating }
async function rate(song: Song, score: number) {
  if (busy.value) return
  if (!user.value) { navigate('/login'); return }
  busy.value = true; feedback.value = ''
  try { const result = await request<{ score: number }>('/api/v1/songs/' + song.id + '/rating/', { method: 'PUT', body: JSON.stringify({ score }) }); ratings.value = { ...ratings.value, [song.id]: result.score }; feedback.value = '评分已保存' }
  catch (failure) { feedback.value = message(failure) } finally { busy.value = false }
}
async function action(song: Song, kind: 'favorite' | 'unfavorite' | 'remove' | 'lists') {
  if (busy.value) return
  if (!user.value) { navigate('/login'); return }
  if ((kind === 'favorite' || kind === 'unfavorite') && !favoritesReady.value) return
  const current = generation
  busy.value = true; feedback.value = ''
  try {
    if (kind === 'lists') { lists.value = await request<Playlist[]>('/api/v1/playlists/'); selectedSong.value = song; selectedList.value = '' }
    else if (kind === 'remove' && props.playlistId) { await request('/api/v1/playlists/' + props.playlistId + '/songs/' + song.id + '/', { method: 'DELETE' }); emit('changed') }
    else {
      const remove = kind === 'unfavorite' || isFavorite(song)
      await request('/api/v1/favorites/' + song.id + '/', { method: remove ? 'DELETE' : 'PUT' })
      if (current !== generation) return
      const ids = new Set(favoriteIds.value)
      if (remove) ids.delete(song.id); else ids.add(song.id)
      favoriteIds.value = ids
      if (props.favoriteMode && remove) emit('changed')
    }
  } catch (failure) { feedback.value = message(failure) } finally { busy.value = false }
}
async function addToList() {
  if (busy.value || !selectedSong.value || !selectedList.value) return
  busy.value = true
  try { await request('/api/v1/playlists/' + selectedList.value + '/songs/' + selectedSong.value.id + '/', { method: 'PUT' }); feedback.value = '已加入歌单'; selectedSong.value = null }
  catch (failure) { feedback.value = message(failure) } finally { busy.value = false }
}
function duration(ms: number) { return Math.floor(ms / 60000) + ':' + String(Math.floor(ms / 1000) % 60).padStart(2, '0') }
function rank(song: Song, index: number) { return String(props.ranks?.[song.id] ?? (props.indexOffset ?? 0) + index + 1).padStart(2, '0') }
</script>
<template><div><p v-if="favoritesError" role="alert" class="error-text">收藏状态加载失败：{{ favoritesError }} <button @click="loadFavorites">重试</button></p><p v-if="feedback" role="status" class="inline-note">{{ feedback }}</p><div v-if="selectedSong" class="inline-form"><strong>将《{{ selectedSong.title }}》加入歌单</strong><select v-model="selectedList" aria-label="选择歌单"><option value="">选择歌单</option><option v-for="list in lists" :key="list.id" :value="list.id">{{ list.name }}</option></select><button :disabled="!selectedList || busy" @click="addToList">确认加入</button><button :disabled="busy" @click="selectedSong = null">取消</button><span v-if="!lists.length">还没有歌单，<button @click="navigate('/playlists')">去创建</button></span></div><div class="song-list"><article v-for="(song, index) in songs" :key="song.id" class="song-row"><span class="song-index">{{ rank(song, index) }}</span><button class="song-cover" :disabled="!song.playable" :aria-label="'播放' + song.title" @click="player?.playQueue(songs, index)">▶</button><div class="song-info"><button class="text-button song-title" @click="navigate('/songs/' + song.id)">{{ song.title }}</button><p>{{ song.artist }}<span v-if="song.album"> · {{ song.album }}</span></p><p v-if="explanations?.[song.id]" class="explanation">{{ explanations[song.id] }}</p><slot name="metadata" :song="song" /><div class="mini-tags"><span v-for="tag in song.tags" :key="tag.id">{{ tag.name }}</span><span v-if="!song.playable">暂不可播放</span></div></div><span class="duration">{{ duration(song.duration_ms) }}</span><div class="song-actions"><button class="favorite-button" :class="{ 'is-favorite': isFavorite(song) }" :aria-pressed="isFavorite(song)" :aria-label="(isFavorite(song) ? '取消收藏' : '收藏') + song.title" :disabled="busy || (!!user && !favoritesReady)" @click="action(song, 'favorite')"><span class="favorite-heart" aria-hidden="true">{{ isFavorite(song) ? '♥' : '♡' }}</span> {{ isFavorite(song) ? '已收藏' : '收藏' }}</button><button v-if="showUnfavorite" :disabled="busy" @click="action(song, 'unfavorite')">取消收藏</button><div class="rating-control" role="group" :aria-label="'给' + song.title + '评分'"><button v-for="score in 5" :key="score" class="rating-star" :class="{ 'is-rated': score <= (rating(song) || 0) }" :aria-label="score + '分'" :aria-pressed="score === rating(song)" :disabled="busy" @click="rate(song, score)">★</button><span class="rating-value">{{ rating(song) ? rating(song) + '/5' : '未评分' }}</span></div><button :disabled="busy" @click="action(song, playlistId ? 'remove' : 'lists')">{{ playlistId ? '移出歌单' : '加入歌单' }}</button></div></article></div></div></template>
