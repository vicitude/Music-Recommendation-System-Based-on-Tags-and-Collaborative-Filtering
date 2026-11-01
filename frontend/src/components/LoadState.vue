<script setup lang="ts">
defineProps<{ loading: boolean; error: string }>()
defineEmits<{ retry: [] }>()
</script>
<template><p v-if="loading" role="status" class="loading-copy">正在加载音乐…</p><p v-if="error" class="error-text" role="alert">{{ error }} <button :disabled="loading" @click="$emit('retry')">重试</button></p></template>
