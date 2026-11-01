import { ref } from 'vue'
import { ApiError, refreshCsrf, request } from './api/client'
import type { User } from './api/types'

export const user = ref<User | null>(null)
export const notice = ref('')
export const ready = ref(false)
export const message = (error: unknown) => error instanceof Error ? error.message : '操作失败，请重试'

export async function initialize(): Promise<void> {
  try { await refreshCsrf(); user.value = await request<User>('/api/v1/me/') }
  catch (error) { if (!(error instanceof ApiError && error.body.error_code === 'AUTH_REQUIRED')) notice.value = message(error) }
  finally { ready.value = true }
}
