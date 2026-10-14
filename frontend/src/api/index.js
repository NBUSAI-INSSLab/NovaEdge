import axios from 'axios'

const TOKEN_KEY = 'novaedge_token'

export const http = axios.create({
  baseURL: '/api/v1',
  timeout: 30000
})

http.interceptors.request.use((config) => {
  const token = localStorage.getItem(TOKEN_KEY)
  if (token) config.headers.Authorization = `Bearer ${token}`
  return config
})

/** 统一错误提示回调，由 App 层注册，避免在 api 层直接依赖 UI */
let onUnauthorized = null
let onError = null

export function registerHandlers({ unauthorized, error }) {
  onUnauthorized = unauthorized
  onError = error
}

http.interceptors.response.use(
  (response) => {
    const body = response.data
    if (body && typeof body === 'object' && 'code' in body) {
      if (body.code !== 0) {
        // 1001 为「分片未传完」等业务中间态，不当作错误弹出
        if (body.code !== 1001 && onError) onError(body.message || '操作失败')
      }
      return body
    }
    return body
  },
  (err) => {
    const status = err?.response?.status
    const message = err?.response?.data?.message
    if (status === 401) {
      if (onUnauthorized) onUnauthorized()
      return Promise.reject(new Error(message || '登录已过期'))
    }
    const text = message || err.message || '网络异常，请检查后端服务是否已启动'
    if (onError) onError(text)
    return Promise.reject(new Error(text))
  }
)

export const tokenStore = {
  get: () => localStorage.getItem(TOKEN_KEY) || '',
  set: (value) => localStorage.setItem(TOKEN_KEY, value),
  clear: () => localStorage.removeItem(TOKEN_KEY)
}

/**
 * 给媒体访问地址附加访问令牌。
 * 浏览器的 <img> / <video> 无法自定义请求头，因此后端对预览类接口
 * 同时支持 ?token= 查询参数鉴权（校验逻辑与请求头方式完全一致）。
 */
export function mediaUrl(path) {
  if (!path) return ''
  const token = tokenStore.get()
  if (!token) return path
  return `${path}${path.includes('?') ? '&' : '?'}token=${encodeURIComponent(token)}`
}

/* ----------------------------- 接口定义 ----------------------------- */
export const api = {
  auth: {
    login: (data) => http.post('/auth/login', data),
    profile: () => http.get('/auth/profile'),
    logout: () => http.post('/auth/logout'),
    changePassword: (data) => http.post('/auth/change-password', data)
  },
  dashboard: {
    overview: () => http.get('/dashboard/overview'),
    distribution: () => http.get('/dashboard/node-distribution'),
    trend: (hours = 24) => http.get('/dashboard/trend', { params: { hours } }),
    topNodes: (limit = 8) => http.get('/dashboard/top-nodes', { params: { limit } }),
    recent: (limit = 8) => http.get('/dashboard/recent', { params: { limit } }),
    metricRanking: (limit = 10) => http.get('/dashboard/metric-ranking', { params: { limit } }),
    offlineNodes: () => http.get('/dashboard/offline-nodes')
  },
  nodes: {
    list: (params) => http.get('/nodes', { params }),
    specs: () => http.get('/nodes/specs'),
    detail: (id) => http.get(`/nodes/${id}`),
    create: (data) => http.post('/nodes', data),
    update: (id, data) => http.put(`/nodes/${id}`, data),
    remove: (id) => http.delete(`/nodes/${id}`),
    toggle: (id) => http.post(`/nodes/${id}/toggle`),
    resetCredential: (id) => http.post(`/nodes/${id}/reset-credential`),
    latest: (id) => http.get(`/nodes/${id}/latest`),
    latestAll: () => http.get('/nodes/latest-all'),
    telemetry: (id, params) => http.get(`/nodes/${id}/telemetry`, { params }),
    heartbeats: (id, params) => http.get(`/nodes/${id}/heartbeats`, { params }),
    logs: (id, params) => http.get(`/nodes/${id}/logs`, { params }),
    statistics: (id) => http.get(`/nodes/${id}/statistics`),
    groups: () => http.get('/nodes/groups'),
    createGroup: (data) => http.post('/nodes/groups', data),
    updateGroup: (id, data) => http.put(`/nodes/groups/${id}`, data),
    removeGroup: (id) => http.delete(`/nodes/groups/${id}`)
  },
  butler: {
    chat: (data) => http.post('/butler/chat', data),
    messages: (params) => http.get('/butler/messages', { params }),
    sessions: () => http.get('/butler/sessions'),
    tools: () => http.get('/butler/tools'),
    config: () => http.get('/butler/config'),
    saveConfig: (data) => http.put('/butler/config', data),
    testConfig: () => http.post('/butler/config/test'),
    reports: (params) => http.get('/butler/reports', { params }),
    report: (id) => http.get(`/butler/reports/${id}`),
    generateReport: (data) => http.post('/butler/reports/generate', data),
    removeReport: (id) => http.delete(`/butler/reports/${id}`),
    downloadReport: (id) => `${http.defaults.baseURL}/butler/reports/${id}/download`,
    downloadUrl: (id) => {
      const token = localStorage.getItem(TOKEN_KEY) || ''
      return `${http.defaults.baseURL}/butler/reports/${id}/download?token=${encodeURIComponent(token)}`
    }
  },
  media: {
    list: (params) => http.get('/media', { params }),
    detail: (id) => http.get(`/media/${id}`),
    update: (id, data) => http.put(`/media/${id}`, data),
    remove: (id) => http.delete(`/media/${id}`),
    batchDelete: (ids) => http.post('/media/batch-delete', { ids }),
    statistics: () => http.get('/media/statistics'),
    uploads: (params) => http.get('/media/uploads', { params })
  },
  alerts: {
    dicts: () => http.get('/alerts/dicts'),
    summary: () => http.get('/alerts/summary'),
    rules: (params) => http.get('/alerts/rules', { params }),
    createRule: (data) => http.post('/alerts/rules', data),
    updateRule: (id, data) => http.put(`/alerts/rules/${id}`, data),
    removeRule: (id) => http.delete(`/alerts/rules/${id}`),
    records: (params) => http.get('/alerts/records', { params }),
    ack: (id) => http.post(`/alerts/records/${id}/ack`),
    clear: (id) => http.post(`/alerts/records/${id}/clear`),
    batchAck: (ids) => http.post('/alerts/records/batch-ack', { ids })
  },
  commands: {
    catalog: () => http.get('/commands/catalog'),
    list: (params) => http.get('/commands', { params }),
    detail: (id) => http.get(`/commands/${id}`),
    issue: (data) => http.post('/commands', data),
    cancel: (id) => http.post(`/commands/${id}/cancel`),
    scanTimeout: () => http.post('/commands/scan-timeout'),
    pendingCount: () => http.get('/commands/pending/count')
  },
  metrics: {
    list: (params) => http.get('/metrics', { params }),
    categories: () => http.get('/metrics/categories'),
    create: (data) => http.post('/metrics', data),
    update: (id, data) => http.put(`/metrics/${id}`, data),
    remove: (id) => http.delete(`/metrics/${id}`)
  },
  system: {
    info: () => http.get('/system/info'),
    configs: () => http.get('/system/configs'),
    updateConfig: (key, data) => http.put(`/system/configs/${key}`, data),
    rollup: (hours) => http.post('/system/maintenance/rollup', { hours }),
    cleanup: (data) => http.post('/system/maintenance/cleanup', data),
    storageUsage: () => http.get('/system/storage-usage'),
    endpoints: () => http.get('/meta/endpoints')
  },
  users: {
    list: (params) => http.get('/users', { params }),
    roles: () => http.get('/users/roles'),
    create: (data) => http.post('/users', data),
    update: (id, data) => http.put(`/users/${id}`, data),
    remove: (id) => http.delete(`/users/${id}`),
    auditLogs: (params) => http.get('/users/audit-logs', { params })
  }
}

/* ----------------------------- 工具函数 ----------------------------- */
export function fmtTime(value, withSeconds = true) {
  if (!value) return '—'
  const date = value instanceof Date ? value : new Date(value)
  if (Number.isNaN(date.getTime())) return '—'
  const pad = (n) => String(n).padStart(2, '0')
  const base = `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ` +
    `${pad(date.getHours())}:${pad(date.getMinutes())}`
  return withSeconds ? `${base}:${pad(date.getSeconds())}` : base
}

export function fmtTimeShort(value) {
  if (!value) return '—'
  const date = value instanceof Date ? value : new Date(value)
  if (Number.isNaN(date.getTime())) return '—'
  const pad = (n) => String(n).padStart(2, '0')
  return `${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`
}

export function fmtDuration(seconds) {
  const total = Math.max(Math.floor(Number(seconds) || 0), 0)
  const day = Math.floor(total / 86400)
  const hour = Math.floor((total % 86400) / 3600)
  const minute = Math.floor((total % 3600) / 60)
  if (day > 0) return `${day} 天 ${hour} 小时`
  if (hour > 0) return `${hour} 小时 ${minute} 分`
  return `${minute} 分`
}

export function fmtNumber(value, digits = 0) {
  const num = Number(value)
  if (!Number.isFinite(num)) return '—'
  return num.toLocaleString('zh-CN', { minimumFractionDigits: digits, maximumFractionDigits: digits })
}

export function fmtBytes(bytes) {
  const value = Number(bytes) || 0
  if (value < 1024) return `${value.toFixed(0)} B`
  const units = ['KB', 'MB', 'GB', 'TB']
  let size = value / 1024
  let index = 0
  while (size >= 1024 && index < units.length - 1) { size /= 1024; index += 1 }
  return `${size.toFixed(size >= 100 ? 0 : 1)} ${units[index]}`
}

export function relativeTime(value) {
  if (!value) return '从未'
  const date = value instanceof Date ? value : new Date(value)
  const diff = (Date.now() - date.getTime()) / 1000
  if (!Number.isFinite(diff)) return '—'
  if (diff < 60) return '刚刚'
  if (diff < 3600) return `${Math.floor(diff / 60)} 分钟前`
  if (diff < 86400) return `${Math.floor(diff / 3600)} 小时前`
  if (diff < 86400 * 30) return `${Math.floor(diff / 86400)} 天前`
  return fmtTime(value, false)
}
