<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { ApiError, request } from '../api/client'
import type { SongPage } from '../api/types'
import { useResource } from '../use-resource'
import { navigate } from '../router'
import LoadState from '../components/LoadState.vue'
import SongList from '../components/SongList.vue'
const page = ref(1)
const { data, loading, error, load } = useResource(async () => {
  let result: SongPage
  try { result = await request<SongPage>('/api/v1/favorites/?page=' + page.value + '&page_size=20') }
  catch (failure) {
    if (!(failure instanceof ApiError) || failure.body.error_code !== 'NOT_FOUND' || page.value <= 1) throw failure
    result = await request<SongPage>('/api/v1/favorites/?page=1&page_size=20')
    page.value = 1
  }
  const last = Math.max(1, Math.ceil(result.count / result.page_size))
  if (page.value > last) { page.value = last; result = await request<SongPage>('/api/v1/favorites/?page=' + page.value + '&page_size=20') }
  return result
})
onMounted(load)
function turn(delta: number) { page.value += delta; void load() }
</script>
<template><section class="content-card list-card"><p class="section-kicker">YOUR COLLECTION</p><h2>留住喜欢的声音</h2><LoadState :loading="loading" :error="error" @retry="load" /><template v-if="data && !loading && !error"><SongList :songs="data.results" favorite-mode @changed="load" /><div v-if="!data.count" class="empty-copy">还没有收藏歌曲。<button @click="navigate('/discover')">去发现音乐</button></div><div v-if="data.count" class="pagination"><button :disabled="page <= 1" @click="turn(-1)">上一页</button><span>共 {{ data.count }} 首 · 第 {{ data.page }} 页</span><button :disabled="data.page * data.page_size >= data.count" @click="turn(1)">下一页</button></div></template></section></template>
