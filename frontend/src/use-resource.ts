import { onUnmounted, ref, shallowRef } from 'vue'
import { message } from './session'

export function useResource<T>(fetcher: () => Promise<T>) {
  const data = shallowRef<T | null>(null), loading = ref(false), error = ref('')
  let revision = 0
  onUnmounted(() => { revision++ })
  async function load(): Promise<void> {
    const current = ++revision
    loading.value = true; error.value = ''
    try { const result = await fetcher(); if (current === revision) data.value = result }
    catch (failure) { if (current === revision) error.value = message(failure) }
    finally { if (current === revision) loading.value = false }
  }
  return { data, loading, error, load }
}
