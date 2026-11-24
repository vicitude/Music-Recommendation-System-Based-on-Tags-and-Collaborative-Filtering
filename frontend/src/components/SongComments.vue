<script setup lang="ts">
import { computed, onUnmounted, ref, shallowRef, watch } from 'vue'
import { ApiError, request } from '../api/client'
import type { CommentItem, CommentsPage } from '../api/types'
import { message, user } from '../session'
import { navigate } from '../router'
import LoadState from './LoadState.vue'

const props = defineProps<{ songId: number }>()
const data = shallowRef<CommentsPage | null>(null)
const page = ref(1), loading = ref(false), error = ref('')
const content = ref(''), submitting = ref(false), actionError = ref('')
const confirming = ref<number | null>(null), deleting = ref<number | null>(null)
const trimmed = computed(() => content.value.trim())
const characterCount = computed(() => Array.from(trimmed.value).length)
const canSubmit = computed(() => !!user.value && characterCount.value >= 1 && characterCount.value <= 500 && !submitting.value && deleting.value === null)
const dateFormat = new Intl.DateTimeFormat('zh-CN', { year: 'numeric', month: 'long', day: 'numeric', hour: '2-digit', minute: '2-digit', hour12: false })
let revision = 0, disposed = false
function active(current: number) { return !disposed && current === revision }
function requestContext(current: number) {
  const ownerId = user.value?.id, songId = props.songId
  return () => active(current) && ownerId === user.value?.id && songId === props.songId
}
async function load(target = page.value) {
  if (disposed) return
  const current = ++revision, songId = props.songId
  page.value = target; loading.value = true; error.value = ''
  confirming.value = null; deleting.value = null; submitting.value = false; actionError.value = ''
  try {
    const result = await request<CommentsPage>('/api/v1/songs/' + songId + '/comments/?page=' + target, {}, requestContext(current))
    if (!active(current)) return
    if (target > 1 && !result.items.length) { await load(1); return }
    data.value = result
  } catch (failure) {
    if (!active(current)) return
    if (target > 1 && failure instanceof ApiError && failure.body.error_code === 'NOT_FOUND' && failure.body.details.includes('page')) {
      await load(1)
      return
    }
    error.value = message(failure)
  }
  finally { if (active(current)) loading.value = false }
}
watch(() => [props.songId, user.value?.id], () => {
  revision++; data.value = null; content.value = ''; page.value = 1
  void load(1)
}, { immediate: true, flush: 'sync' })
onUnmounted(() => { disposed = true; revision++ })
async function submit() {
  if (disposed || !canSubmit.value) return
  const current = revision, songId = props.songId, submitted = trimmed.value
  submitting.value = true; actionError.value = ''
  try {
    await request<CommentItem>('/api/v1/songs/' + songId + '/comments/', { method: 'POST', body: JSON.stringify({ content: submitted }) }, requestContext(current))
    if (!active(current)) return
    content.value = ''
    await load(1)
  } catch (failure) { if (active(current)) actionError.value = message(failure) }
  finally { if (active(current)) submitting.value = false }
}
function canDelete(item: CommentItem) { return item.can_delete === true && item.author.id === user.value?.id }
function askDelete(item: CommentItem) {
  if (disposed || loading.value || submitting.value || deleting.value !== null || !canDelete(item)) return
  confirming.value = item.id; actionError.value = ''
}
function cancelDelete() { if (deleting.value === null) confirming.value = null }
async function remove(item: CommentItem) {
  if (disposed || confirming.value !== item.id || !canDelete(item) || submitting.value || deleting.value !== null || loading.value) return
  const current = revision, target = page.value
  deleting.value = item.id; actionError.value = ''
  try {
    await request('/api/v1/comments/' + item.id + '/', { method: 'DELETE' }, requestContext(current))
    if (!active(current)) return
    await load(target)
  } catch (failure) { if (active(current)) actionError.value = message(failure) }
  finally { if (active(current)) deleting.value = null }
}
function turn(delta: number) {
  if (disposed || loading.value || submitting.value || deleting.value !== null || !data.value) return
  const target = page.value + delta
  if (target < 1 || target > Math.max(1, Math.ceil(data.value.total / data.value.page_size))) return
  void load(target)
}
function localDate(value: string) {
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? '时间未知' : dateFormat.format(date)
}
</script>

<template>
  <section class="song-comments" aria-labelledby="song-comments-title" :aria-busy="loading">
    <h3 id="song-comments-title">歌曲评论</h3>
    <form v-if="user" class="comment-form" @submit.prevent="submit">
      <label for="song-comment-content">发表你的评论（1—500字）</label>
      <textarea id="song-comment-content" v-model="content" rows="3" :disabled="submitting" aria-describedby="song-comment-count" />
      <div class="comment-actions"><span id="song-comment-count" :class="{ 'comment-invalid': characterCount > 500 }">{{ characterCount }} / 500字（去除首尾空白）</span><button class="comment-button" type="submit" :disabled="!canSubmit">{{ submitting ? '提交中…' : '发表评论' }}</button></div>
    </form>
    <p v-else class="comment-login">登录后可以发表评论。<button class="comment-button" @click="navigate('/login')">去登录</button></p>
    <p v-if="actionError" class="comment-error" role="alert">{{ actionError }}</p>
    <LoadState :loading="loading" :error="error" @retry="load()" />
    <template v-if="data && !loading && !error">
      <p v-if="!data.items.length" class="empty-copy">还没有评论，来分享你的感受吧。</p>
      <ul v-else class="comment-list">
        <li v-for="item in data.items" :key="item.id" class="comment-item">
          <div class="comment-meta"><button class="comment-button" @click="navigate('/users/' + item.author.id)">{{ item.author.username }}</button><time :datetime="item.created_at">{{ localDate(item.created_at) }}</time></div>
          <p class="comment-content">{{ item.content }}</p>
          <div v-if="canDelete(item)" class="comment-actions">
            <template v-if="confirming === item.id"><span>确定删除这条评论？删除后无法恢复。</span><button class="comment-button" :disabled="deleting !== null" @click="remove(item)">{{ deleting === item.id ? '删除中…' : '确认删除' }}</button><button class="comment-button" :disabled="deleting !== null" @click="cancelDelete">取消</button></template>
            <button v-else class="comment-button" :disabled="submitting || deleting !== null" @click="askDelete(item)">删除评论</button>
          </div>
        </li>
      </ul>
    </template>
    <nav v-if="data && data.total" class="comment-pagination" aria-label="评论分页">
      <button class="comment-button" :disabled="loading || submitting || deleting !== null || page <= 1" @click="turn(-1)">上一页</button><span role="status">共 {{ data.total }} 条 · 第 {{ page }} 页</span><button class="comment-button" :disabled="loading || submitting || deleting !== null || page * data.page_size >= data.total" @click="turn(1)">下一页</button>
    </nav>
  </section>
</template>

<style scoped>
.song-comments { margin-top: 20px; border-top: 1px solid #dedbe5; padding-top: 12px; min-width: 0; }
.comment-form { display: grid; gap: 8px; font-size: 13px; }
.comment-form textarea { box-sizing: border-box; width: 100%; min-width: 0; resize: vertical; padding: 10px; border: 1px solid #bcb8c8; border-radius: 10px; font: inherit; }
.comment-actions, .comment-meta, .comment-pagination, .comment-login { display: flex; flex-wrap: wrap; align-items: center; gap: 8px 12px; }
.comment-actions, .comment-pagination { font-size: 13px; }
.comment-button { display: inline-block; flex-shrink: 0; min-height: 44px; padding: 8px 14px; border-radius: 20px; background: #282633; color: #fff; font-size: 13px; }
.comment-list { list-style: none; padding: 0; margin: 12px 0; }
.comment-item { padding: 12px 0; border-bottom: 1px solid #e9e6ee; min-width: 0; }
.comment-meta { font-size: 13px; overflow-wrap: anywhere; }
.comment-meta time { color: #625b70; font-size: 12px; }
.comment-content { white-space: pre-wrap; overflow-wrap: anywhere; margin: 8px 0; line-height: 1.6; font-size: 14px; }
.comment-error, .comment-invalid { color: #a12635; }
.comment-pagination { justify-content: center; margin-top: 12px; }
@media (max-width: 600px) { .comment-actions > span { flex-basis: 100%; } }
</style>
