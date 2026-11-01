<script setup lang="ts">
import { ref } from 'vue'
import { request } from '../api/client'
import type { User } from '../api/types'
import { message, user } from '../session'
import { navigate } from '../router'
const username = ref(''), password = ref(''), busy = ref(false), error = ref('')
async function submit() {
  if (busy.value) return
  busy.value = true; error.value = ''
  try { user.value = await request<User>('/api/v1/auth/login/', { method: 'POST', body: JSON.stringify({ username: username.value, password: password.value }) }); password.value = ''; navigate(user.value.onboarding_completed ? '/daily' : '/onboarding') }
  catch (failure) { error.value = message(failure) } finally { busy.value = false }
}
</script>
<template><section class="content-card auth-card"><p class="section-kicker">欢迎回来</p><h2>继续你的音乐旅程</h2><form @submit.prevent="submit"><label>用户名<input v-model="username" required autocomplete="username" maxlength="30" /></label><label>密码<input v-model="password" type="password" required autocomplete="current-password" maxlength="128" /></label><p v-if="error" role="alert" class="error-text">{{ error }}</p><button class="primary-button" :disabled="busy">{{ busy ? '登录中…' : '登录' }}</button></form><p>还没有账号？<button class="text-button" @click="navigate('/register')">创建账号</button></p></section></template>
