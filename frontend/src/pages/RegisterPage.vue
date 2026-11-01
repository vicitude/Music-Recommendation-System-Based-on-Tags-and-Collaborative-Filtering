<script setup lang="ts">
import { ref } from 'vue'
import { request } from '../api/client'
import { message, notice } from '../session'
import { navigate } from '../router'
const username = ref(''), password = ref(''), confirm = ref(''), busy = ref(false), error = ref('')
async function submit() {
  if (busy.value) return
  if (password.value !== confirm.value) { error.value = '两次密码不一致'; return }
  busy.value = true; error.value = ''
  try { await request('/api/v1/auth/register/', { method: 'POST', body: JSON.stringify({ username: username.value, password: password.value }) }); password.value = ''; confirm.value = ''; notice.value = '注册成功，请登录'; navigate('/login') }
  catch (failure) { error.value = message(failure) } finally { busy.value = false }
}
</script>
<template><section class="content-card auth-card"><p class="section-kicker">从这里开始</p><h2>创建你的音乐账号</h2><form @submit.prevent="submit"><label>用户名<input v-model="username" required minlength="3" maxlength="30" autocomplete="username" /><small>3—30位英文字母、数字或下划线</small></label><label>密码<input v-model="password" type="password" required minlength="10" maxlength="128" autocomplete="new-password" /></label><label>确认密码<input v-model="confirm" type="password" required autocomplete="new-password" /></label><p v-if="error" class="error-text" role="alert">{{ error }}</p><button class="primary-button" :disabled="busy">{{ busy ? '提交中…' : '注册' }}</button></form><button class="text-button" @click="navigate('/login')">已有账号，去登录</button></section></template>
