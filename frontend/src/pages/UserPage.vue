<script setup lang="ts">
import { onUnmounted, ref, shallowRef, watch } from 'vue'
import { ApiError, request } from '../api/client'
import type { UserSummary } from '../api/types'
import { message, user } from '../session'
import { currentPath, navigate } from '../router'
import LoadState from '../components/LoadState.vue'

const targetId = currentPath().split('/')[2]
const data = shallowRef<UserSummary | null>(null)
const loading = ref(false), busy = ref(false), error = ref(''), actionError = ref(''), uncertain = ref(false)
let revision = 0, disposed = false
function context(current: number) {
  const owner = user.value, path = currentPath()
  return () => !disposed && revision === current && user.value === owner && currentPath() === path
}
function failureMessage(failure: unknown) {
  return failure instanceof ApiError && failure.body.error_code === 'NOT_FOUND' ? '该用户不存在或暂时不可访问' : message(failure)
}
async function load() {
  if (disposed || busy.value || !user.value) return
  const current = ++revision, isCurrent = context(current)
  loading.value = true; error.value = ''; actionError.value = ''
  try {
    const result = await request<UserSummary>('/api/v1/users/' + targetId + '/', {}, isCurrent)
    if (isCurrent()) { data.value = result; uncertain.value = false }
  } catch (failure) { if (isCurrent()) { data.value = null; error.value = failureMessage(failure) } }
  finally { if (isCurrent()) loading.value = false }
}
async function toggleFollow() {
  if (disposed || !user.value || loading.value || busy.value || uncertain.value || !data.value || data.value.is_self) return
  const current = ++revision, isCurrent = context(current), method = data.value.is_following ? 'DELETE' : 'PUT'
  busy.value = true; actionError.value = ''
  try {
    const result = await request<UserSummary>('/api/v1/users/' + targetId + '/follow/', { method }, isCurrent)
    if (isCurrent()) data.value = result
  } catch (failure) {
    if (isCurrent()) { uncertain.value = true; actionError.value = failureMessage(failure) + '。操作结果尚未确认，请刷新状态核实后再操作。' }
  } finally { if (isCurrent()) busy.value = false }
}
watch(user, () => {
  revision++; data.value = null; loading.value = false; busy.value = false; error.value = ''; actionError.value = ''; uncertain.value = false
  void load()
}, { immediate: true, flush: 'sync' })
onUnmounted(() => { disposed = true; revision++ })
</script>
<template>
  <section class="content-card social-page" :aria-busy="loading">
    <LoadState :loading="loading" :error="error" @retry="load" />
    <template v-if="data && !loading && !error">
      <div class="section-heading"><h2>{{ data.username }}<small v-if="data.is_self"> · 我</small></h2><button v-if="!data.is_self" class="primary-button" :disabled="busy || uncertain" @click="toggleFollow">{{ busy ? '处理中…' : data.is_following ? '取消关注' : '关注' }}</button></div>
      <div class="actions"><button @click="navigate('/users/' + data.id + '/following')">关注 {{ data.following_count }}</button><button @click="navigate('/users/' + data.id + '/followers')">粉丝 {{ data.follower_count }}</button><button v-if="data.is_self" @click="navigate('/profile')">回到私人中心</button></div>
    </template>
    <p v-if="actionError" role="alert">{{ actionError }}</p>
    <button :disabled="loading || busy" @click="load">{{ uncertain ? '刷新状态核实' : '刷新主页' }}</button>
  </section>
</template>
<style scoped>
.social-page { min-width: 0; }.social-page h2 { overflow-wrap: anywhere; }.social-page button { min-height: 44px; }.actions { flex-wrap: wrap; margin: 12px 0; }small { font-size: 14px; }[role="alert"] { color: #a32a21; overflow-wrap: anywhere; }
</style>
