<script setup lang="ts">
import { computed, onMounted, onUnmounted, provide, ref, watch } from 'vue'
import { configureClient, request } from './api/client'
import { currentPath, navigate, routeName } from './router'
import { initialize, message, notice, ready, user } from './session'
import { playerKey, type PlayerHandle } from './player-context'
import AudioPlayer from './components/AudioPlayer.vue'
import LoginPage from './pages/LoginPage.vue'
import RegisterPage from './pages/RegisterPage.vue'
import OnboardingPage from './pages/OnboardingPage.vue'
import DiscoverPage from './pages/DiscoverPage.vue'
import SongPage from './pages/SongPage.vue'
import FavoritesPage from './pages/FavoritesPage.vue'
import PlaylistsPage from './pages/PlaylistsPage.vue'
import PlaylistPage from './pages/PlaylistPage.vue'
import DailyPage from './pages/DailyPage.vue'
const path = ref(currentPath()), player = ref<PlayerHandle | null>(null), loggingOut = ref(false)
const route = computed(() => { path.value; return routeName() })
const protectedPage = computed(() => ['daily', 'onboarding', 'favorites', 'playlists', 'playlist'].includes(route.value))
const pages = { login: LoginPage, register: RegisterPage, onboarding: OnboardingPage, discover: DiscoverPage, song: SongPage, favorites: FavoritesPage, playlists: PlaylistsPage, playlist: PlaylistPage, daily: DailyPage }
const component = computed(() => route.value === 'not-found' ? null : pages[route.value])
const pageTitle = computed(() => ({ login: '欢迎回来', register: '加入音律', onboarding: '选择你的兴趣', discover: '发现音乐', song: '歌曲详情', favorites: '我的收藏', playlists: '我的歌单', playlist: '歌单详情', daily: '每日推荐', 'not-found': '页面未找到' }[route.value]))
provide(playerKey, { playSong: async song => { await player.value?.playSong(song) }, selectLocal: async file => { await player.value?.selectLocal(file) }, pause: () => player.value?.pause(), seek: value => player.value?.seek(value), stop: async () => { await player.value?.stop() }, leaveLocal: () => player.value?.leaveLocal() })
configureClient({ authRequired: () => { if (user.value) notice.value = '登录状态已失效，请重新登录'; user.value = null }, csrfFailed: () => { notice.value = '请求校验信息已更新，请手动重试刚才的操作' } })
watch([ready, user, path], () => { if (ready.value && protectedPage.value && !user.value) navigate('/login') })
function refreshPath() { player.value?.leaveLocal(); path.value = currentPath() }
onMounted(() => { window.addEventListener('hashchange', refreshPath); void initialize() })
onUnmounted(() => window.removeEventListener('hashchange', refreshPath))
async function logout() {
  if (loggingOut.value) return
  loggingOut.value = true
  try { await player.value?.stop(); await request('/api/v1/auth/logout/', { method: 'POST' }); user.value = null; notice.value = '已退出登录'; navigate('/login') }
  catch (failure) { notice.value = message(failure) } finally { loggingOut.value = false }
}
</script>
<template><div class="app-shell"><header class="topbar"><button class="brand" @click="navigate('/daily')">音律<span>·</span></button><nav class="main-nav" aria-label="主导航"><button v-for="item in [{ path: '/daily', name: 'daily', label: '每日推荐' }, { path: '/discover', name: 'discover', label: '发现音乐' }, { path: '/favorites', name: 'favorites', label: '收藏' }, { path: '/playlists', name: 'playlists', label: '歌单' }]" :key="item.path" :class="{ active: route === item.name || (route === 'playlist' && item.name === 'playlists') }" @click="navigate(item.path)">{{ item.label }}</button></nav><div class="account-actions"><template v-if="user"><span>{{ user.username }}</span><button class="profile-button" :disabled="loggingOut" @click="logout">{{ loggingOut ? '退出中…' : '退出' }}</button></template><button v-else class="profile-button" @click="navigate('/login')">登录 / 注册</button></div></header><main class="page-container"><div class="eyebrow">MUSIC RECOMMENDER · ADAPTIVE MIX</div><h1>{{ pageTitle }}</h1><div v-if="notice" class="global-notice" role="status"><span>{{ notice }}</span><button aria-label="关闭提示" @click="notice = ''">×</button></div><p v-if="!ready" role="status" class="loading-copy">正在检查登录状态…</p><component :is="component" v-else-if="component && (!protectedPage || user)" :key="(user?.id ?? 'guest') + path" /><section v-else-if="!component" class="content-card empty-state"><h2>这里暂时没有页面</h2><button class="primary-button" @click="navigate('/discover')">去发现音乐</button></section></main><AudioPlayer ref="player" /></div></template>
