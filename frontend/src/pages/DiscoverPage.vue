<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { request } from '../api/client'
import type { SongPage, Tag } from '../api/types'
import { useResource } from '../use-resource'
import LoadState from '../components/LoadState.vue'
import SongList from '../components/SongList.vue'
const query = ref(''), tag = ref(''), page = ref(1)
let appliedQuery = '', appliedTag = ''
const tags = useResource(() => request<Tag[]>('/api/v1/tags/'))
const { data, loading, error, load } = useResource(() => {
  const params = new URLSearchParams({ page: String(page.value), page_size: '20' })
  if (appliedQuery) params.set('q', appliedQuery)
  if (appliedTag) params.set('tag_id', appliedTag)
  return request<SongPage>('/api/v1/songs/?' + params)
})
onMounted(() => { void tags.load(); void load() })
function search() { appliedQuery = query.value.trim(); appliedTag = tag.value; page.value = 1; void load() }
function turn(delta: number) { page.value += delta; void load() }
</script>
<template><section class="content-card list-card"><div class="section-heading"><div><p class="section-kicker">FIND YOUR SOUND</p><h2>探索曲库</h2></div><span v-if="data" class="muted">共 {{ data.count }} 首</span></div><form class="filter-form" @submit.prevent="search"><input v-model="query" maxlength="100" placeholder="搜索歌曲或歌手" aria-label="搜索歌曲或歌手" /><select v-model="tag" aria-label="筛选标签"><option value="">全部标签</option><option v-for="item in tags.data.value || []" :key="item.id" :value="item.id">{{ item.name }}</option></select><button class="primary-button" :disabled="loading">搜索</button></form><LoadState :loading="tags.loading.value" :error="tags.error.value" @retry="tags.load" /><LoadState :loading="loading" :error="error" @retry="load" /><template v-if="data && !loading && !error"><SongList :songs="data.results" :index-offset="(data.page - 1) * data.page_size" /><p v-if="!data.results.length" class="empty-copy">没有找到歌曲。试试其他关键词或标签。</p><div class="pagination"><button :disabled="page <= 1" @click="turn(-1)">上一页</button><span>第 {{ data.page }} 页</span><button :disabled="data.page * data.page_size >= data.count" @click="turn(1)">下一页</button></div></template></section></template>
