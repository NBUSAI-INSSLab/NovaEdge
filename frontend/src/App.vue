<script setup>
import { onMounted, onUnmounted, watch } from 'vue'
import { useRouter } from 'vue-router'
import { registerHandlers } from '@/api'
import { useToastStore } from '@/stores/toast'
import { useRealtimeStore } from '@/stores/realtime'
import { useUserStore } from '@/stores/user'
import AppIcon from '@/components/AppIcon.vue'

const router = useRouter()
const toast = useToastStore()
const realtime = useRealtimeStore()
const userStore = useUserStore()

/** 把 API 层的错误/失效事件接到全局提示与路由跳转 */
registerHandlers({
  unauthorized: () => {
    if (userStore.isLoggedIn) {
      userStore.clear()
      toast.warning('登录状态已失效，请重新登录')
    }
    if (router.currentRoute.value.name !== 'login') {
      router.push({ name: 'login', query: { redirect: router.currentRoute.value.fullPath } })
    }
  },
  error: (message) => toast.error(message)
})

let retryTimer = null

function startRealtime() {
  realtime.connect({
    onAlert: (payload) => {
      if (payload.action === 'created') {
        toast.warning(`告警：${payload.alert?.title || ''}`)
      }
    }
  }, 'global')
}

watch(
  () => userStore.isLoggedIn,
  (logged) => {
    if (logged) {
      startRealtime()
      clearInterval(retryTimer)
      retryTimer = setInterval(() => {
        if (userStore.isLoggedIn && !realtime.connected) realtime.connect()
      }, 12000)
    } else {
      realtime.disconnect()
      clearInterval(retryTimer)
    }
  },
  { immediate: true }
)

onMounted(() => {
  if (userStore.isLoggedIn && !userStore.loaded) userStore.fetchProfile()
})

onUnmounted(() => {
  realtime.disconnect()
  clearInterval(retryTimer)
})

const toastIcon = (type) => ({
  success: 'check-circle', error: 'x-circle', warning: 'alert-circle', info: 'info'
}[type] || 'info')
</script>

<template>
  <router-view v-slot="{ Component }">
    <transition name="fade" mode="out-in">
      <component :is="Component" />
    </transition>
  </router-view>

  <div class="toast-stack">
    <div v-for="item in toast.items" :key="item.id" class="toast" :class="item.type">
      <AppIcon :name="toastIcon(item.type)" :size="16" />
      <span>{{ item.message }}</span>
    </div>
  </div>
</template>
