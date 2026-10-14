import { defineStore } from 'pinia'
import { tokenStore } from '@/api'

/**
 * 实时通道：基于 SSE 接收平台推送（节点状态、遥测、告警、媒体、指令）。
 * 断线由浏览器 EventSource 自动重连；同时对外暴露在线状态供顶栏展示。
 */
export const useRealtimeStore = defineStore('realtime', {
  state: () => ({
    connected: false,
    lastEventAt: 0,
    latestTelemetry: {},      // { nodeId: { metric: {value, ts} } }
    onlineNodes: 0,
    activeAlerts: 0,
    mqttConnected: false,
    events: [],               // 最近事件流（最多 60 条）
    handlers: {}              // 各页面注册的事件处理器，按 key 去重
  }),
  getters: {
    connectedLabel: (state) => (state.connected ? '实时通道正常' : '实时通道断开')
  },
  actions: {
    /**
     * 建立实时通道，并按 key 注册事件处理器。
     * 多个页面共用同一条 SSE 连接，各自注册自己的回调，互不覆盖。
     */
    connect(handlers = {}, key = 'default') {
      if (handlers && Object.keys(handlers).length) this.handlers[key] = handlers
      if (this._source) return
      const token = tokenStore.get()
      if (!token) return
      const source = new EventSource(`/api/v1/stream/events?token=${encodeURIComponent(token)}`)
      this._source = source

      source.addEventListener('connected', () => {
        this.connected = true
        this.lastEventAt = Date.now()
      })
      source.addEventListener('telemetry', (event) => this._onTelemetry(event))
      source.addEventListener('node', (event) => this._onNode(event))
      source.addEventListener('alert', (event) => this._onAlert(event))
      source.addEventListener('media', (event) => this._onMedia(event))
      source.addEventListener('command', (event) => this._onCommand(event))
      source.addEventListener('system', (event) => this._push('系统', this._parse(event)))

      source.onerror = () => {
        this.connected = false
      }
    },
    /** 把事件广播给全部已注册的页面处理器 */
    _dispatch(eventName, payload) {
      Object.values(this.handlers).forEach((set) => {
        try {
          set?.[eventName]?.(payload)
        } catch (e) { /* 单个页面回调异常不影响其它页面 */ }
      })
    },
    disconnect() {
      if (this._source) {
        this._source.close()
        this._source = null
      }
      this.connected = false
      this.handlers = {}
    },
    _parse(event) {
      try {
        const body = JSON.parse(event.data)
        return body.data ?? body
      } catch (e) {
        return null
      }
    },
    _push(kind, payload, level = 'info') {
      if (!payload) return
      this.events.unshift({ kind, payload, level, at: Date.now(), id: `${Date.now()}_${Math.random()}` })
      if (this.events.length > 60) this.events.pop()
    },
    _onTelemetry(event) {
      const data = this._parse(event)
      if (!data) return
      this.lastEventAt = Date.now()
      const bucket = this.latestTelemetry[data.node_id] || (this.latestTelemetry[data.node_id] = {})
      Object.entries(data.samples || {}).forEach(([metric, sample]) => {
        bucket[metric] = { value: sample.value_num ?? sample.value_str, ts: sample.ts }
      })
      this._push('遥测', `${data.node_name} 上报 ${data.count} 条数据`)
      this._dispatch('onTelemetry', data)
    },
    _onNode(event) {
      const payload = this._parse(event)
      if (!payload) return
      this.lastEventAt = Date.now()
      if (payload.action === 'online') {
        this._push('节点', `${payload.node?.name} 已上线`, 'success')
      } else if (payload.action === 'heartbeat') {
        this._push('心跳', `${payload.node?.name} CPU ${payload.node?.cpu_percent}%`)
      } else if (payload.action === 'log') {
        this._push('日志', `${payload.node_name} 上报 ${payload.count} 条日志`, payload.level === 'error' ? 'error' : 'info')
      } else if (payload.action === 'mqtt_connected') {
        this.mqttConnected = true
      } else if (payload.action === 'deleted') {
        this._push('节点', '节点已删除', 'warning')
      }
      this._dispatch('onNode', payload)
    },
    _onAlert(event) {
      const payload = this._parse(event)
      if (!payload) return
      this.lastEventAt = Date.now()
      if (payload.action === 'created') {
        this._push('告警', payload.alert?.title || '新告警', payload.alert?.severity === 'critical' ? 'error' : 'warning')
      } else if (payload.action === 'cleared') {
        this._push('告警', `${payload.alert?.title || ''} 已恢复`, 'success')
      }
      this._dispatch('onAlert', payload)
    },
    _onMedia(event) {
      const payload = this._parse(event)
      if (!payload) return
      this.lastEventAt = Date.now()
      if (payload.action === 'created') {
        this._push('媒体', `${payload.media?.node_name} 上传${payload.media?.file_type_label} ${payload.media?.file_name}`)
      }
      this._dispatch('onMedia', payload)
    },
    _onCommand(event) {
      const payload = this._parse(event)
      if (!payload) return
      this.lastEventAt = Date.now()
      if (payload.action === 'acked') {
        this._push('指令', `${payload.node_name} 执行${payload.command?.command_label || '指令'}：${payload.command?.status_label}`)
      }
      this._dispatch('onCommand', payload)
    }
  }
})
