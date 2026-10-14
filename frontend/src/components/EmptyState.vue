<script setup>
import AppIcon from './AppIcon.vue'

defineProps({
  icon: { type: String, default: 'inbox' },
  title: { type: String, default: '暂无数据' },
  description: { type: String, default: '' },
  actionText: { type: String, default: '' }
})
const emit = defineEmits(['action'])
</script>

<template>
  <div class="empty-state">
    <div class="icon-wrap">
      <AppIcon :name="icon" :size="26" :stroke="1.5" />
    </div>
    <div class="title">{{ title }}</div>
    <div v-if="description" class="desc">{{ description }}</div>
    <button v-if="actionText" class="btn btn-sm mt-6" @click="emit('action')">{{ actionText }}</button>
  </div>
</template>

<style scoped>
.empty-state {
  display: flex; flex-direction: column; align-items: center; justify-content: center;
  gap: 8px; padding: 56px 20px; color: var(--c-text-2);
}
.icon-wrap {
  width: 54px; height: 54px; border-radius: 15px;
  display: flex; align-items: center; justify-content: center;
  background: var(--c-surface-3); color: var(--c-text-3);
}
.title { font-size: 14px; font-weight: 600; color: var(--c-text); }
.desc { font-size: 12.5px; color: var(--c-text-3); text-align: center; max-width: 420px; }
</style>
