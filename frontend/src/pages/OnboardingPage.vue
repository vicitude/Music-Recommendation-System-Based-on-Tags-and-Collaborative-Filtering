<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { request } from '../api/client'
import type { Interests, Tag } from '../api/types'
import { useResource } from '../use-resource'
import { message, user } from '../session'
import { navigate } from '../router'
import LoadState from '../components/LoadState.vue'
const selected = ref<number[]>([]), busy = ref(false), feedback = ref('')
const { data, loading, error, load } = useResource(async () => {
  const [tags, interests] = await Promise.all([request<Tag[]>('/api/v1/tags/'), request<Interests>('/api/v1/me/interests/')])
  selected.value = interests.tag_ids
  return tags
})
onMounted(load)
function toggle(id: number) { selected.value = selected.value.includes(id) ? selected.value.filter(value => value !== id) : selected.value.length < 5 ? [...selected.value, id] : selected.value }
async function save(skip = false) {
  if (busy.value) return
  const ownerId = user.value?.id
  busy.value = true; feedback.value = ''
  try {
    await request<Interests>('/api/v1/me/interests/', { method: 'PUT', body: JSON.stringify({ tag_ids: skip ? [] : selected.value }) })
    if (user.value?.id === ownerId && user.value) { user.value = { ...user.value, onboarding_completed: true }; navigate('/daily') }
  } catch (failure) { feedback.value = message(failure) } finally { busy.value = false }
}
</script>
<template><section class="content-card"><p class="section-kicker">START WITH A FEW TAGS</p><h2>先告诉我们，你想听什么。</h2><p>选择 3—5 个风格、情绪或场景标签，帮助新用户开始推荐。也可跳过，从热门歌曲探索。</p><LoadState :loading="loading" :error="error" @retry="load" /><div v-if="data && !loading && !error"><div class="tag-grid"><button v-for="tag in data" :key="tag.id" class="tag-chip" :class="{ selected: selected.includes(tag.id) }" :aria-pressed="selected.includes(tag.id)" :disabled="busy || (!selected.includes(tag.id) && selected.length >= 5)" @click="toggle(tag.id)">{{ tag.name }}</button></div><p v-if="!data.length">暂无可选标签，可以先跳过。</p><p>已选 {{ selected.length }} / 5</p><div class="actions"><button class="primary-button" :disabled="busy || selected.length < 3 || selected.length > 5" @click="save()">保存兴趣</button><button :disabled="busy" @click="save(true)">跳过并清空兴趣</button></div></div><p v-if="feedback" role="alert" class="error-text">{{ feedback }}</p></section></template>
