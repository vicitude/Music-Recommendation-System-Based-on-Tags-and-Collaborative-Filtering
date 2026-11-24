<script setup lang="ts">
import { computed, onUnmounted, ref, shallowRef, watch } from 'vue'
import { ApiError, request } from '../api/client'
import type { UserConnections, UserSummary } from '../api/types'
import { message, user } from '../session'
import { currentPath, navigate } from '../router'
import LoadState from '../components/LoadState.vue'

const segments = currentPath().split('/'), targetId = segments[2], direction = segments[3]
const label = direction === 'following' ? '关注' : '粉丝'
const owner = shallowRef<UserSummary | null>(null), data = shallowRef<UserConnections | null>(null)
const page = ref(1), loading = ref(false), error = ref('')
const totalPages = computed(() => Math.max(1, Math.ceil((data.value?.count ?? 0) / 20)))
let revision = 0, disposed = false
function context(current: number) {
  const account = user.value, path = currentPath(), requestedPage = page.value
  return () => !disposed && revision === current && user.value === account && currentPath() === path && requestedPage === page.value
}
async function load(target = page.value, resetUsed = false) {
  if (disposed || !user.value) return
  page.value = target
  const current = ++revision, isCurrent = context(current)
  loading.value = true; error.value = ''; data.value = null
  try {
    const summary = await request<UserSummary>('/api/v1/users/' + targetId + '/', {}, isCurrent)
    if (!isCurrent()) return
    owner.value = summary
    const result = await request<UserConnections>('/api/v1/users/' + targetId + '/' + direction + '/?page=' + target, {}, isCurrent)
    if (!isCurrent()) return
    if (target > 1 && !result.results.length && !resetUsed) { await load(1, true); return }
    data.value = result
  } catch (failure) {
    if (!isCurrent()) return
    if (target > 1 && !resetUsed && failure instanceof ApiError && failure.body.error_code === 'NOT_FOUND' && failure.body.details.includes('page')) { await load(1, true); return }
    if (failure instanceof ApiError && failure.body.error_code === 'NOT_FOUND' && !failure.body.details.includes('page')) owner.value = null
    error.value = failure instanceof ApiError && failure.body.error_code === 'NOT_FOUND' ? '该用户不存在或暂时不可访问' : message(failure)
  } finally { if (isCurrent()) loading.value = false }
}
function turn(delta: number) {
  if (disposed || loading.value || !data.value) return
  const next = page.value + delta
  if (next >= 1 && next <= totalPages.value) void load(next)
}
watch(user, () => {
  revision++; owner.value = null; data.value = null; page.value = 1; error.value = ''; loading.value = false
  void load(1)
}, { immediate: true, flush: 'sync' })
onUnmounted(() => { disposed = true; revision++ })
</script>
<template>
  <section class="content-card social-connections" :aria-busy="loading">
    <div class="section-heading"><h2>{{ owner?.username ?? '用户' }}的{{ label }}</h2><button @click="navigate('/users/' + targetId)">返回主页</button></div>
    <LoadState :loading="loading" :error="error" @retry="load()" />
    <template v-if="data && !loading && !error">
      <p v-if="!data.results.length" class="empty-copy">暂时没有{{ label }}。</p>
      <ul v-else><li v-for="person in data.results" :key="person.id"><button @click="navigate('/users/' + person.id)">{{ person.username }}</button><span v-if="person.is_self">我</span><span v-else-if="person.is_following">已关注</span></li></ul>
      <nav class="pagination" :aria-label="label + '分页'"><button :disabled="page <= 1" @click="turn(-1)">上一页</button><span role="status">共 {{ data.count }} 人 · 第 {{ page }} / {{ totalPages }} 页</span><button :disabled="page >= totalPages" @click="turn(1)">下一页</button></nav>
    </template>
  </section>
</template>
<style scoped>
.social-connections { min-width: 0; }.social-connections h2 { overflow-wrap: anywhere; }.social-connections button { min-height: 44px; }.social-connections ul { list-style: none; padding: 0; }.social-connections li { display: flex; align-items: center; gap: 12px; border-bottom: 1px solid #dedbe5; padding: 6px 0; }.social-connections li button { text-align: left; overflow-wrap: anywhere; min-width: 0; }.social-connections li span { white-space: nowrap; color: #847784; }.pagination { flex-wrap: wrap; }
</style>
