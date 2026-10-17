<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api, fmtTime } from '@/api'
import { useUserStore } from '@/stores/user'
import { useRealtimeStore } from '@/stores/realtime'
import { useThemeStore, THEMES } from '@/stores/theme'
import AppIcon from '@/components/AppIcon.vue'

const route = useRoute()
const router = useRouter()
const userStore = useUserStore()
const realtime = useRealtimeStore()
const theme = useThemeStore()

const collapsed = ref(false)
const now = ref(new Date())
const alertSummary = ref({ active_total: 0, by_severity: {} })
const showEvents = ref(false)

setInterval(() => { now.value = new Date() }, 1000)

const menu = computed(() => {
  const layout = router.getRoutes().find((item) => item.path === '/' && item.children?.length)
  const source = layout?.children || []
  return source
    .filter((item) => !item.meta?.hidden && !item.meta?.parent)
    .filter((item) => !item.meta?.roles || item.meta.roles.includes(userStore.role))
    .map((item) => ({
      name: item.name,
      title: item.meta?.title,
      icon: item.meta?.icon,
      path: router.resolve({ name: item.name }).path
    }))
})

const currentTitle = computed(() => route.meta?.title || '总览看板')
const isActive = (item) => {
  const target = item.name
  if (route.name === target) return true
  if (target === 'nodes' && route.name === 'node-detail') return true
  return false
}

async function loadAlertSummary() {
  try {
    const res = await api.alerts.summary()
    if (res.code === 0) alertSummary.value = res.data
  } catch (e) { /* 静默 */ }
}

onMounted(loadAlertSummary)
setInterval(loadAlertSummary, 30000)

async function handleLogout() {
  await userStore.logout()
  router.push({ name: 'login' })
}
</script>

<template>
  <div class="layout" :class="{ collapsed }">
    <!-- ------------------------------ 侧边栏 ------------------------------ -->
    <aside class="sidebar">
      <div class="brand">
        <div class="brand-logo">
          <svg viewBox="0 0 40 40" width="30" height="30">
            <circle cx="20" cy="20" r="3.6" style="fill: var(--c-accent)" />
            <circle cx="20" cy="20" r="8" fill="none" style="stroke: var(--c-accent)" stroke-opacity="0.6" stroke-width="2" />
            <circle cx="20" cy="20" r="13" fill="none" stroke="#FFFFFF" stroke-opacity="0.35" stroke-width="2" />
            <circle cx="20" cy="7.5" r="2.4" fill="#FFFFFF" />
            <circle cx="20" cy="32.5" r="2.4" fill="#FFFFFF" />
            <circle cx="8" cy="20" r="2.4" fill="#FFFFFF" opacity="0.75" />
            <circle cx="32" cy="20" r="2.4" fill="#FFFFFF" opacity="0.75" />
          </svg>
        </div>
        <div v-if="!collapsed" class="brand-text">
          <div class="brand-name">NovaEdge</div>
          <div class="brand-sub">边缘智算管理平台</div>
        </div>
      </div>

      <nav class="nav">
        <router-link
          v-for="item in menu"
          :key="item.name"
          :to="item.path"
          class="nav-item"
          :class="{ active: isActive(item) }"
          :title="item.title"
        >
          <AppIcon :name="item.icon" :size="18" />
          <span v-if="!collapsed">{{ item.title }}</span>
        </router-link>
      </nav>

      <div class="sidebar-foot">
        <div v-if="!collapsed" class="realtime-card" :class="{ ok: realtime.connected }">
          <div class="row gap-6">
            <i class="dot" />
            <span>{{ realtime.connected ? '实时通道已连接' : '实时通道断开' }}</span>
          </div>
          <div class="tiny muted-2 mt-6">
            最后事件 {{ realtime.lastEventAt ? fmtTime(realtime.lastEventAt) : '—' }}
          </div>
        </div>
        <button class="collapse-btn" :title="collapsed ? '展开侧栏' : '收起侧栏'" @click="collapsed = !collapsed">
          <AppIcon :name="collapsed ? 'chevron-right' : 'chevron-left'" :size="15" />
          <span v-if="!collapsed">收起侧栏</span>
        </button>
      </div>
    </aside>

    <!-- ------------------------------ 主区域 ------------------------------ -->
    <div class="main">
      <header class="header" @click="theme.closePanel()">
        <div class="row gap-12">
          <div class="theme-anchor" @click.stop>
            <button
              class="icon-btn"
              :class="{ on: theme.visible }"
              title="界面配色"
              @click="theme.togglePanel()"
            >
              <AppIcon name="palette" :size="17" />
            </button>
            <transition name="fade">
              <div v-if="theme.visible" class="theme-panel">
                <div class="theme-head">界面配色</div>
                <button
                  v-for="item in THEMES"
                  :key="item.key"
                  class="theme-item"
                  :class="{ active: theme.current === item.key }"
                  @click="theme.apply(item.key); theme.closePanel()"
                >
                  <span class="swatches">
                    <i :style="{ background: item.colors[0] }" />
                    <i :style="{ background: item.colors[1] }" />
                    <i :style="{ background: item.colors[2] }" />
                  </span>
                  <span class="theme-meta">
                    <strong>{{ item.label }}</strong>
                    <small>{{ item.desc }}</small>
                  </span>
                  <AppIcon v-if="theme.current === item.key" name="check" :size="16" class="theme-check" />
                </button>
              </div>
            </transition>
          </div>
          <h1 class="page-title">{{ currentTitle }}</h1>
          <span class="tag tag-primary">v1.0.0</span>
        </div>

        <div class="header-right">
          <div class="clock mono">{{ fmtTime(now) }}</div>

          <button class="icon-btn" title="实时事件" @click="showEvents = !showEvents">
            <AppIcon name="radio" :size="17" />
            <i v-if="realtime.connected" class="live-dot" />
          </button>

          <router-link to="/alerts" class="icon-btn" title="告警">
            <AppIcon name="alert" :size="17" />
            <i v-if="alertSummary.active_total" class="badge">{{ alertSummary.active_total > 99 ? '99+' : alertSummary.active_total }}</i>
          </router-link>

          <div class="divider" />

          <div class="user">
            <div class="avatar">{{ userStore.displayName.slice(0, 1) }}</div>
            <div class="user-meta">
              <div class="user-name">{{ userStore.displayName }}</div>
              <div class="user-role">{{ userStore.profile?.role_label }}</div>
            </div>
            <button class="icon-btn" title="退出登录" @click="handleLogout">
              <AppIcon name="logout" :size="16" />
            </button>
          </div>
        </div>
      </header>

      <!-- 实时事件浮层 -->
      <transition name="fade">
        <div v-if="showEvents" class="events-panel">
          <div class="row-between mb-10">
            <strong>实时事件流</strong>
            <button class="btn btn-ghost btn-sm" @click="realtime.events = []">清空</button>
          </div>
          <div v-if="!realtime.events.length" class="muted small">暂无事件，节点上报后将实时显示</div>
          <div v-else class="event-list">
            <div v-for="item in realtime.events" :key="item.id" class="event-row" :class="item.level">
              <span class="tag" :class="{
                'tag-primary': item.kind === '遥测',
                'tag-teal': item.kind === '节点' || item.kind === '心跳',
                'tag-critical': item.level === 'error',
                'tag-major': item.level === 'warning',
                'tag-online': item.level === 'success'
              }">{{ item.kind }}</span>
              <span class="grow ellipsis">{{ item.payload?.title || item.payload?.node?.name || '' }}
                {{ typeof item.payload === 'string' ? item.payload : '' }}
              </span>
              <span class="tiny muted-2 mono">{{ fmtTime(item.at).slice(11) }}</span>
            </div>
          </div>
        </div>
      </transition>

      <main class="content" @click="showEvents && (showEvents = false); theme.closePanel()">
        <router-view v-slot="{ Component }">
          <transition name="fade" mode="out-in">
            <component :is="Component" />
          </transition>
        </router-view>
        <footer class="page-footer">
          NovaEdge 边缘智算管理平台 · 边缘节点数据汇聚与智能运维
        </footer>
      </main>
    </div>
  </div>
</template>

<style scoped>
.layout { display: flex; height: 100vh; overflow: hidden; }

/* ------------------------------ 侧边栏 ------------------------------ */
.sidebar {
  width: var(--sidebar-w);
  flex-shrink: 0;
  display: flex; flex-direction: column;
  background: var(--sidebar-bg);
  transition: width 0.2s ease;
}
.collapsed .sidebar { width: 66px; }

.brand {
  display: flex; align-items: center; gap: 11px;
  height: var(--header-h); padding: 0 16px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.09);
  flex-shrink: 0;
}
.brand-logo { width: 30px; display: flex; justify-content: center; }
.brand-text { min-width: 0; }
.brand-name { color: #fff; font-size: 15.5px; font-weight: 700; letter-spacing: 0.3px; line-height: 1.25; }
.brand-sub { color: var(--sidebar-text-2); font-size: 11px; line-height: 1.3; }

.nav { flex: 1; padding: 12px 10px; overflow-y: auto; display: flex; flex-direction: column; gap: 3px; }
.nav-item {
  display: flex; align-items: center; gap: 11px;
  height: 40px; padding: 0 12px;
  border-radius: 9px;
  color: var(--sidebar-text);
  font-size: 13.5px;
  white-space: nowrap;
  transition: background 0.16s, color 0.16s;
}
.nav-item:hover { background: var(--sidebar-hover); color: #fff; }
.nav-item.active {
  background: var(--sidebar-active);
  color: var(--sidebar-text-active);
  font-weight: 600;
  box-shadow: inset 2px 0 0 var(--c-accent);
}
.collapsed .nav-item { justify-content: center; padding: 0; }

.sidebar-foot { padding: 10px; border-top: 1px solid rgba(255, 255, 255, 0.09); }
.realtime-card {
  padding: 9px 11px; border-radius: 9px;
  background: rgba(255, 255, 255, 0.06);
  font-size: 11.5px; color: var(--sidebar-text);
  margin-bottom: 8px;
}
.realtime-card .dot { width: 6px; height: 6px; border-radius: 50%; background: #E4A23C; display: inline-block; }
.realtime-card.ok .dot { background: #4FD48A; box-shadow: 0 0 6px rgba(79, 212, 138, 0.8); }
.collapse-btn {
  width: 100%; height: 32px; display: flex; align-items: center; justify-content: center; gap: 6px;
  border: none; border-radius: 8px; background: transparent;
  color: var(--sidebar-text-2); font-size: 12px; font-family: inherit; cursor: pointer;
}
.collapse-btn:hover { background: var(--sidebar-hover); color: #fff; }

/* ------------------------------ 主区域 ------------------------------ */
.main { flex: 1; min-width: 0; display: flex; flex-direction: column; position: relative; }
.header {
  height: var(--header-h); flex-shrink: 0;
  display: flex; align-items: center; justify-content: space-between; gap: 16px;
  padding: 0 22px;
  background: var(--c-surface);
  border-bottom: 1px solid var(--c-border);
  position: relative; z-index: 20;
}
.page-title { margin: 0; font-size: 17px; font-weight: 600; }

/* ------------------------------ 配色面板 ------------------------------ */
.theme-anchor { position: relative; }
.icon-btn.on {
  color: var(--c-primary);
  border-color: var(--c-primary-300);
  background: var(--c-primary-50);
}
.theme-panel {
  position: absolute; top: calc(100% + 10px); left: 0; z-index: 80;
  width: 252px; padding: 8px;
  background: var(--c-surface); border: 1px solid var(--c-border);
  border-radius: var(--radius-lg); box-shadow: var(--shadow-lg);
}
.theme-head {
  padding: 6px 10px 8px;
  font-size: 12px; font-weight: 600; color: var(--c-text-3);
  letter-spacing: 1px;
}
.theme-item {
  width: 100%; display: flex; align-items: center; gap: 11px;
  padding: 8px 10px; border: 1px solid transparent; border-radius: 10px;
  background: transparent; cursor: pointer; text-align: left; font-family: inherit;
  transition: background 0.14s, border-color 0.14s;
}
.theme-item:hover { background: var(--c-surface-2); border-color: var(--c-border); }
.theme-item.active { background: var(--c-primary-50); border-color: var(--c-primary-300); }
.swatches { display: flex; gap: 3px; flex-shrink: 0; }
.swatches i {
  width: 15px; height: 15px; border-radius: 5px;
  box-shadow: inset 0 0 0 1px rgba(0, 0, 0, 0.08);
}
.theme-meta { flex: 1; min-width: 0; line-height: 1.3; }
.theme-meta strong { display: block; font-size: 13px; color: var(--c-text); font-weight: 600; }
.theme-meta small { font-size: 11px; color: var(--c-text-3); }
.theme-check { color: var(--c-primary); flex-shrink: 0; }

.header-right { display: flex; align-items: center; gap: 8px; }
.clock { font-size: 12.5px; color: var(--c-text-2); padding-right: 6px; }
.icon-btn {
  position: relative;
  width: 34px; height: 34px; display: flex; align-items: center; justify-content: center;
  border: 1px solid var(--c-border); border-radius: 9px;
  background: var(--c-surface); color: var(--c-text-2); cursor: pointer;
  transition: all 0.16s;
}
.icon-btn:hover { color: var(--c-primary); border-color: var(--c-primary-300); background: var(--c-primary-50); }
.live-dot {
  position: absolute; top: 6px; right: 6px;
  width: 7px; height: 7px; border-radius: 50%; background: #2FB27C;
  box-shadow: 0 0 0 2px var(--c-surface);
  animation: blink 1.6s ease-in-out infinite;
}
@keyframes blink { 0%, 100% { opacity: 1; } 50% { opacity: 0.3; } }
.badge {
  position: absolute; top: -5px; right: -5px;
  min-width: 16px; height: 16px; padding: 0 4px;
  border-radius: 8px; background: var(--c-red); color: #fff;
  font-size: 10px; font-weight: 600; font-style: normal;
  display: flex; align-items: center; justify-content: center;
}
.divider { width: 1px; height: 24px; background: var(--c-border); margin: 0 4px; }
.user { display: flex; align-items: center; gap: 9px; }
.avatar {
  width: 32px; height: 32px; border-radius: 9px;
  display: flex; align-items: center; justify-content: center;
  background: linear-gradient(135deg, var(--c-primary), var(--c-primary-700));
  color: #fff; font-size: 13.5px; font-weight: 600;
}
.user-meta { line-height: 1.25; }
.user-name { font-size: 13px; font-weight: 600; }
.user-role { font-size: 11px; color: var(--c-text-3); }

.content {
  flex: 1; overflow-y: auto; padding: 20px 22px 0;
  display: flex; flex-direction: column;
}
.page-footer {
  margin-top: auto; padding: 20px 0 16px;
  text-align: center; font-size: 11.5px; color: var(--c-text-3);
}

/* ------------------------------ 事件浮层 ------------------------------ */
.events-panel {
  position: absolute; top: calc(var(--header-h) + 6px); right: 22px;
  width: 388px; max-height: 62vh; overflow-y: auto;
  padding: 14px 16px; z-index: 60;
  background: var(--c-surface); border: 1px solid var(--c-border);
  border-radius: var(--radius-lg); box-shadow: var(--shadow-lg);
}
.event-list { display: flex; flex-direction: column; gap: 7px; }
.event-row {
  display: flex; align-items: center; gap: 8px;
  padding: 6px 8px; border-radius: 7px; font-size: 12.5px;
  background: var(--c-surface-2);
}

@media (max-width: 820px) {
  .user-meta, .clock { display: none; }
}
</style>
