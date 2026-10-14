import { defineStore } from 'pinia'
import { api, tokenStore } from '@/api'

export const useUserStore = defineStore('user', {
  state: () => ({
    token: tokenStore.get(),
    profile: null,
    loaded: false
  }),
  getters: {
    isLoggedIn: (state) => Boolean(state.token),
    role: (state) => state.profile?.role || 'viewer',
    displayName: (state) => state.profile?.real_name || state.profile?.username || '未登录',
    isAdmin() { return this.role === 'admin' },
    canOperate() { return ['admin', 'operator'].includes(this.role) }
  },
  actions: {
    async login(username, password) {
      const res = await api.auth.login({ username, password })
      if (res.code !== 0) throw new Error(res.message)
      this.token = res.data.token
      this.profile = res.data.user
      this.loaded = true
      tokenStore.set(res.data.token)
      return res.data.user
    },
    async fetchProfile() {
      if (!this.token) return null
      try {
        const res = await api.auth.profile()
        if (res.code === 0) {
          this.profile = res.data
          this.loaded = true
          return this.profile
        }
      } catch (e) {
        this.clear()
      }
      return null
    },
    clear() {
      this.token = ''
      this.profile = null
      this.loaded = false
      tokenStore.clear()
    },
    async logout() {
      try { await api.auth.logout() } catch (e) { /* 忽略退出接口异常 */ }
      this.clear()
    }
  }
})
