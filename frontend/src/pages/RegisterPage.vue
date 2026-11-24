<script setup lang="ts">
import { ref } from 'vue'
import { ApiError, request } from '../api/client'
import { message, notice } from '../session'
import { navigate } from '../router'
const username = ref(''), password = ref(''), confirm = ref(''), busy = ref(false), error = ref('')
async function submit() {
  if (busy.value) return
  if (password.value !== confirm.value) { error.value = '两次密码不一致'; return }
  const normalizedUsername = username.value.trim()
  if (!/^[A-Za-z0-9_]{3,30}$/.test(normalizedUsername)) { error.value = '用户名须为3—30位英文字母、数字或下划线，不能包含中文或空格'; return }
  if (password.value.length < 10 || password.value.length > 128) { error.value = '密码须为10—128个字符'; return }
  if (/^\d+$/.test(password.value)) { error.value = '密码不能只包含数字，请搭配字母等字符'; return }
  busy.value = true; error.value = ''
  try { await request('/api/v1/auth/register/', { method: 'POST', body: JSON.stringify({ username: normalizedUsername, password: password.value }) }); password.value = ''; confirm.value = ''; notice.value = '注册成功，请登录'; navigate('/login') }
  catch (failure) {
    if (failure instanceof ApiError && failure.body.error_code === 'USERNAME_TAKEN') error.value = '这个用户名已被使用，请换一个用户名'
    else if (failure instanceof ApiError && failure.body.error_code === 'VALIDATION_ERROR') {
      const details = failure.body.details ?? []
      error.value = details.includes('password')
        ? '密码未通过安全检查：须为10—128个字符，不能纯数字、过于常见或与用户名太相似。请换一个较长且不包含用户名的密码'
        : details.includes('username') ? '用户名须为3—30位英文字母、数字或下划线' : '注册信息未通过校验，请检查用户名及下方密码规则后重试'
    } else error.value = message(failure)
  } finally { busy.value = false }
}
</script>
<template><section class="content-card auth-card"><p class="section-kicker">从这里开始</p><h2>创建你的音乐账号</h2><form @submit.prevent="submit"><label>用户名<input v-model="username" required minlength="3" maxlength="30" autocomplete="username" /><small>3—30位英文字母、数字或下划线</small></label><label>密码<input v-model="password" type="password" required minlength="10" maxlength="128" autocomplete="new-password" aria-describedby="register-password-help" /><small id="register-password-help">10—128个字符；不能纯数字、过于常见或与用户名太相似。建议使用较长的字母与数字组合，避免包含用户名。</small></label><label>确认密码<input v-model="confirm" type="password" required maxlength="128" autocomplete="new-password" /></label><p v-if="error" class="error-text" role="alert">{{ error }}</p><button class="primary-button" :disabled="busy">{{ busy ? '提交中…' : '注册' }}</button></form><button class="text-button" @click="navigate('/login')">已有账号，去登录</button></section></template>
