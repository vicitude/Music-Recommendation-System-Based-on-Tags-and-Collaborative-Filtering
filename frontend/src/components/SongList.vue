<script setup lang="ts">
import { inject, ref } from 'vue'
import { request } from '../api/client'
import type { Playlist, Song } from '../api/types'
import { playerKey } from '../player-context'
import { message, user } from '../session'
import { navigate } from '../router'
const props = defineProps<{ songs: Song[]; favoriteMode?: boolean; showUnfavorite?: boolean; playlistId?: number; explanations?: Record<number, string>; ranks?: Record<number, number> }>()
const emit = defineEmits<{ changed: [] }>()
const player = inject(playerKey)
const busy = ref(false), feedback = ref(''), lists = ref<Playlist[]>([]), selectedSong = ref<Song | null>(null), selectedList = ref('')
async function action(song: Song, kind: 'favorite' | 'unfavorite' | 'remove' | 'lists') {
  if (busy.value) return
  if (!user.value) { navigate('/login'); return }
  busy.value = true; feedback.value = ''
  try {
    if (kind === 'lists') { lists.value = await request<Playlist[]>('/api/v1/playlists/'); selectedSong.value = song; selectedList.value = '' }
    else if (kind === 'remove' && props.playlistId) { await request('/api/v1/playlists/' + props.playlistId + '/songs/' + song.id + '/', { method: 'DELETE' }); emit('changed') }
    else { const remove = props.favoriteMode || kind === 'unfavorite'; await request('/api/v1/favorites/' + song.id + '/', { method: remove ? 'DELETE' : 'PUT' }); feedback.value = remove ? '已取消收藏' : '已收藏，可手动刷新每日推荐'; emit('changed') }
  } catch (failure) { feedback.value = message(failure) } finally { busy.value = false }
}
async function addToList() {
  if (busy.value || !selectedSong.value || !selectedList.value) return
  busy.value = true
  try { await request('/api/v1/playlists/' + selectedList.value + '/songs/' + selectedSong.value.id + '/', { method: 'PUT' }); feedback.value = '已加入歌单'; selectedSong.value = null }
  catch (failure) { feedback.value = message(failure) } finally { busy.value = false }
}
function duration(ms: number) { return Math.floor(ms / 60000) + ':' + String(Math.floor(ms / 1000) % 60).padStart(2, '0') }
function rank(song: Song, index: number) { return String(props.ranks?.[song.id] ?? index + 1).padStart(2, '0') }
</script>
<template><div><p v-if="feedback" role="status" class="inline-note">{{ feedback }}</p><div v-if="selectedSong" class="inline-form"><strong>将《{{ selectedSong.title }}》加入歌单</strong><select v-model="selectedList" aria-label="选择歌单"><option value="">选择歌单</option><option v-for="list in lists" :key="list.id" :value="list.id">{{ list.name }}</option></select><button :disabled="!selectedList || busy" @click="addToList">确认加入</button><button :disabled="busy" @click="selectedSong = null">取消</button><span v-if="!lists.length">还没有歌单，<button @click="navigate('/playlists')">去创建</button></span></div><div class="song-list"><article v-for="(song, index) in songs" :key="song.id" class="song-row"><span class="song-index">{{ rank(song, index) }}</span><button class="song-cover" :disabled="!song.playable" :aria-label="'播放' + song.title" @click="player?.playSong(song)">▶</button><div class="song-info"><button class="text-button song-title" @click="navigate('/songs/' + song.id)">{{ song.title }}</button><p>{{ song.artist }}<span v-if="song.album"> · {{ song.album }}</span></p><p v-if="explanations?.[song.id]" class="explanation">{{ explanations[song.id] }}</p><div class="mini-tags"><span v-for="tag in song.tags" :key="tag.id">{{ tag.name }}</span><span v-if="!song.playable">暂不可播放</span></div></div><span class="duration">{{ duration(song.duration_ms) }}</span><div class="song-actions"><button :disabled="busy" @click="action(song, 'favorite')">{{ favoriteMode ? '取消收藏' : '收藏' }}</button><button v-if="showUnfavorite" :disabled="busy" @click="action(song, 'unfavorite')">取消收藏</button><button :disabled="busy" @click="action(song, playlistId ? 'remove' : 'lists')">{{ playlistId ? '移出歌单' : '加入歌单' }}</button></div></article></div></div></template>
