<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { request } from '../api/client'
import type { Song } from '../api/types'
import { PlaybackController, type PlaybackMode } from '../playback'
import { notice, user } from '../session'
const audio = ref<HTMLAudioElement | null>(null)
const version = ref(0)
const mode = computed(() => { version.value; return controller?.mode ?? 'list' })
const queueCount = computed(() => { version.value; return controller?.queue.length ?? 0 })
function changeMode(event: Event) { controller?.setMode((event.target as HTMLSelectElement).value as PlaybackMode) }
let controller: PlaybackController | null = null
const title = computed(() => { version.value; return controller?.title ?? '还没有播放音乐' })
const artist = computed(() => { version.value; return controller?.artist ?? '选择一首歌，开启今天的声音' })
onMounted(() => { if (audio.value) controller = new PlaybackController(audio.value, { now: () => performance.now(), uuid: () => crypto.randomUUID(), send: event => request('/api/v1/behaviors/', { method: 'POST', body: JSON.stringify(event) }), delay: ms => new Promise(resolve => setTimeout(resolve, ms)), createUrl: file => URL.createObjectURL(file), revokeUrl: url => URL.revokeObjectURL(url), notify: text => { notice.value = text }, changed: () => { version.value++ } }) })
watch(user, (value, previous) => { if (!value || (previous && previous.id !== value.id)) controller?.cancelOnline() }, { flush: 'sync' })
onUnmounted(() => { controller?.cancelOnline(); if (controller?.localUrl) controller.leaveLocal() })
async function playSong(song: Song) { if (!user.value) { window.location.hash = '/login'; notice.value = '请先登录后在线播放'; return } await controller?.playSong(song) }
async function playQueue(songs: Song[], index: number) { if (!user.value) { window.location.hash = '/login'; notice.value = '请先登录后在线播放'; return } await controller?.playQueue(songs, index) }
async function selectLocal(file: File) { await controller?.selectLocal(file) }
async function openLocal(event: Event) { const input = event.target as HTMLInputElement; const file = input.files?.[0]; if (file) await selectLocal(file); input.value = '' }
function seeked() { if (audio.value && !audio.value.paused && !audio.value.seeking && audio.value.readyState >= 3) controller?.playing() }
function mediaError() { if (audio.value?.error) controller?.mediaError() }
defineExpose({ playSong, playQueue, selectLocal, pause: () => controller?.pause(), seek: (positionMs: number) => controller?.seek(positionMs), stop: async () => { await controller?.stop() }, leaveLocal: () => controller?.leaveLocal() })
</script>
<template><footer class="player-bar"><div class="player-track"><span class="record-mark">♪</span><div><strong>{{ title }}</strong><small>{{ artist }}</small></div></div><audio ref="audio" controls preload="metadata" aria-label="全局音乐播放器" @playing="controller?.playing()" @pause="controller?.freeze()" @waiting="controller?.freeze()" @seeking="controller?.freeze()" @seeked="seeked" @ended="controller?.ended()" @error="mediaError" /><div class="player-controls"><button :disabled="!queueCount" aria-label="上一首" @click="controller?.skip(-1)">上一首</button><button :disabled="!queueCount" aria-label="下一首" @click="controller?.skip(1)">下一首</button><select :value="mode" aria-label="播放模式" @change="changeMode"><option value="list">列表循环</option><option value="single">单曲循环</option><option value="order">顺序播放</option><option value="random">随机播放</option></select></div><label class="local-button">打开本地音频<input type="file" accept="audio/*,.mp3,.wav,.ogg" @change="openLocal" /></label></footer></template>
