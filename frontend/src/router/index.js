import { createRouter, createWebHistory } from 'vue-router'
import { useUserStore } from '@/stores/user'

const routes = [
  {
    path: '/login',
    name: 'login',
    component: () => import('@/views/LoginView.vue'),
    meta: { public: true, title: '登录' }
  },
  {
    path: '/',
    component: () => import('@/layouts/MainLayout.vue'),
    redirect: '/dashboard',
    children: [
      { path: 'dashboard', name: 'dashboard', component: () => import('@/views/DashboardView.vue'), meta: { title: '总览看板', icon: 'dashboard' } },
      { path: 'nodes', name: 'nodes', component: () => import('@/views/NodesView.vue'), meta: { title: '节点管理', icon: 'node' } },
      { path: 'nodes/:id', name: 'node-detail', component: () => import('@/views/NodeDetailView.vue'), meta: { title: '节点详情', hidden: true, parent: 'nodes' } },
      { path: 'monitor', name: 'monitor', component: () => import('@/views/MonitorView.vue'), meta: { title: '数据监控', icon: 'monitor' } },
      { path: 'media', name: 'media', component: () => import('@/views/MediaView.vue'), meta: { title: '数据资产', icon: 'media' } },
      { path: 'alerts', name: 'alerts', component: () => import('@/views/AlertsView.vue'), meta: { title: '告警中心', icon: 'alert' } },
      { path: 'commands', name: 'commands', component: () => import('@/views/CommandsView.vue'), meta: { title: '控制中心', icon: 'command' } },
      { path: 'butler', name: 'butler', component: () => import('@/views/ButlerView.vue'), meta: { title: '智能管家', icon: 'butler' } },
      // 物模型已并入「系统运维 · 物模型」选项卡，旧链接自动跳转
      { path: 'metrics', redirect: { name: 'system', query: { tab: 'metric' } }, meta: { hidden: true, title: '物模型' } },
      { path: 'system', name: 'system', component: () => import('@/views/SystemView.vue'), meta: { title: '系统运维', icon: 'system' } },
      { path: 'users', name: 'users', component: () => import('@/views/UsersView.vue'), meta: { title: '用户权限', icon: 'users', roles: ['admin'] } }
    ]
  },
  { path: '/:pathMatch(.*)*', redirect: '/dashboard' }
]

const router = createRouter({
  history: createWebHistory(),
  routes,
  scrollBehavior: () => ({ top: 0 })
})

router.beforeEach(async (to) => {
  const userStore = useUserStore()
  if (to.meta.public) {
    return userStore.isLoggedIn && to.name === 'login' ? { name: 'dashboard' } : true
  }
  if (!userStore.isLoggedIn) {
    return { name: 'login', query: { redirect: to.fullPath } }
  }
  if (!userStore.loaded) {
    await userStore.fetchProfile()
    if (!userStore.isLoggedIn) return { name: 'login' }
  }
  if (to.meta.roles && !to.meta.roles.includes(userStore.role)) {
    return { name: 'dashboard' }
  }
  return true
})

router.afterEach((to) => {
  const title = to.meta?.title
  document.title = title ? `${title} · NovaEdge 边缘智算管理平台` : 'NovaEdge 边缘智算管理平台'
})

export default router
