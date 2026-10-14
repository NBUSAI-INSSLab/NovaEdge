<script setup>
import AppIcon from './AppIcon.vue'

/** 节点在线状态标签 */
const props = defineProps({
  status: { type: String, default: 'offline' },
  label: { type: String, default: '' }
})

const MAP = {
  online: { text: '在线', cls: 'tag-online' },
  offline: { text: '离线', cls: 'tag-offline' },
  disabled: { text: '已停用', cls: 'tag-disabled' }
}
</script>

<template>
  <span class="tag" :class="(MAP[status] || MAP.offline).cls">
    <i class="dot" :class="{ pulse: status === 'online' }" />
    {{ label || (MAP[status] || MAP.offline).text }}
  </span>
</template>

<style scoped>
.dot.pulse { animation: pulse 1.8s ease-in-out infinite; }
@keyframes pulse {
  0%, 100% { opacity: 1; transform: scale(1); }
  50% { opacity: 0.45; transform: scale(0.82); }
}
</style>
