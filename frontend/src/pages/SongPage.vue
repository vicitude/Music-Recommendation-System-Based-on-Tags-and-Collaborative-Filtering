<script setup lang="ts">
import { onMounted } from 'vue'
import { request } from '../api/client'
import type { Song } from '../api/types'
import { currentPath, navigate } from '../router'
import { useResource } from '../use-resource'
import LoadState from '../components/LoadState.vue'
import SongList from '../components/SongList.vue'
const id = Number(currentPath().split('/').pop())
const { data, loading, error, load } = useResource(() => request<Song>('/api/v1/songs/' + id + '/'))
onMounted(load)
function safeLink(value: string) { try { const url = new URL(value); return ['http:', 'https:'].includes(url.protocol) ? url.href : undefined } catch { return undefined } }
</script>
<template><section class="content-card list-card"><button class="text-button" @click="navigate('/discover')">← 发现音乐</button><LoadState :loading="loading" :error="error" @retry="load" /><template v-if="data && !loading && !error"><p class="section-kicker">TRACK DETAILS</p><h2>{{ data.title }}</h2><SongList :songs="[data]" show-unfavorite /><div class="license-info"><h3>来源与授权说明</h3><p>{{ data.attribution_text || '暂无署名说明' }}</p><p>{{ data.license_name || '暂无公开许可信息' }}</p><a v-if="safeLink(data.source_url)" :href="safeLink(data.source_url)" target="_blank" rel="noopener noreferrer">查看素材来源 ↗</a> <a v-if="safeLink(data.license_url)" :href="safeLink(data.license_url)" target="_blank" rel="noopener noreferrer">查看授权条款 ↗</a></div></template></section></template>
