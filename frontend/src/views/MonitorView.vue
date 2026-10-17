<script setup>
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { api, fmtTime, relativeTime } from '@/api'
import { useRealtimeStore } from '@/stores/realtime'
import { useChartColors } from '@/utils/chartPalette'
import EChart from '@/components/EChart.vue'
import AppIcon from '@/components/AppIcon.vue'
import StatusTag from '@/components/StatusTag.vue'
import EmptyState from '@/components/EmptyState.vue'

const realtime = useRealtimeStore()
const chartC = useChartColors()

const loading = ref(true)
const nodes = ref([])
const latestMap = ref({})          // { nodeId: [metrics] }
const metricDefs = ref([])
const selectedMetrics = ref([])
const compareNodes = ref([])
const historyHours = ref(6)
const seriesData = ref({})         // { `${nodeId}:${metric}`: [points] }
const focusNodeId = ref(null)

// 对比指标多选下拉
const metricOpen = ref(false)
const metricBox = ref(null)

const selectedMetricDefs = computed(() =>
  selectedMetrics.value.map((key) => metricDefs.value.find((item) => item.metric_key === key) || { metric_key: key, name: key, unit: '' })
)

function toggleMetric(key) {
  const index = selectedMetrics.value.indexOf(key)
  if (index >= 0) {
    if (selectedMetrics.value.length === 1) return   // 至少保留一个指标
    selectedMetrics.value.splice(index, 1)
  } else {
    selectedMetrics.value.push(key)
  }
  loadSeries()
}

function clearMetrics() {
  if (!metricDefs.value.length) return
  selectedMetrics.value = [metricDefs.value[0].metric_key]
  loadSeries()
}

function onDocClick(event) {
  if (metricBox.value && !metricBox.value.contains(event.target)) metricOpen.value = false
}

async function loadNodes() {
  const res = await api.nodes.list({ page: 1, page_size: 100 })
  if (res.code === 0) {
    nodes.value = res.data.items
    if (!compareNodes.value.length) {
      compareNodes.value = res.data.items.filter((n) => n.status === 'online').slice(0, 3).map((n) => n.id)
    }
  }
}

async function loadMetrics() {
  const res = await api.metrics.list({ page: 1, page_size: 200 })
  if (res.code === 0) {
    metricDefs.value = res.data.items.filter((item) => !['cpu_percent', 'mem_percent', 'disk_percent', 'net_rx_kbps', 'net_tx_kbps', 'uptime_seconds'].includes(item.metric_key))
  }
}

async function loadLatestAll() {
  // 单次批量请求获取全部节点最新值，避免逐节点并发（并发风暴会拖慢后续页面加载）
  const res = await api.nodes.latestAll().catch(() => null)
  if (res && res.code === 0) latestMap.value = res.data
}

async function loadAll() {
  loading.value = true
  try {
    await Promise.all([loadNodes(), loadMetrics()])
    await loadLatestAll()
    if (!selectedMetrics.value.length && metricDefs.value.length) {
      selectedMetrics.value = [metricDefs.value[0].metric_key]
    }
    await loadSeries()
  } finally {
    loading.value = false
  }
}

async function loadSeries() {
  if (!compareNodes.value.length || !selectedMetrics.value.length) {
    seriesData.value = {}
    return
  }
  const result = {}
  for (const nodeId of compareNodes.value) {
    for (const metric of selectedMetrics.value) {
      const res = await api.nodes.telemetry(nodeId, { metric, hours: historyHours.value, points: 300 })
      if (res.code === 0) result[`${nodeId}:${metric}`] = res.data[metric] || []
    }
  }
  seriesData.value = result
}

let refreshTimer = null

onMounted(() => {
  loadAll()
  document.addEventListener('click', onDocClick)
})

onUnmounted(() => {
  document.removeEventListener('click', onDocClick)
  clearInterval(refreshTimer)
})

// 实时刷新：收到该节点的遥测事件后更新最新值
realtime.connect({
  // 页面级订阅
  onTelemetry: (payload) => {
    const current = latestMap.value[payload.node_id]
    if (!current) return
    const metrics = current.metrics.map((item) => {
      const sample = payload.samples[item.metric_key]
      if (!sample) return item
      return { ...item, value_num: sample.value_num ?? item.value_num, ts: sample.ts }
    })
    latestMap.value = { ...latestMap.value, [payload.node_id]: { ...current, metrics } }
  }
}, 'monitor')

refreshTimer = setInterval(() => { loadLatestAll() }, 30000)

/** 表格列：以节点为行，指标为动态列 */
const tableMetrics = computed(() => {
  const keys = new Set()
  Object.values(latestMap.value).forEach((item) => {
    ;(item.metrics || []).forEach((metric) => {
      if (!['cpu_percent', 'mem_percent', 'disk_percent', 'net_rx_kbps', 'net_tx_kbps', 'uptime_seconds'].includes(metric.metric_key)) {
        keys.add(metric.metric_key)
      }
    })
  })
  return [...keys].slice(0, 8).map((key) => {
    const def = metricDefs.value.find((item) => item.metric_key === key)
    return { key, name: def?.name || key, unit: def?.unit || '' }
  })
})

const monitorRows = computed(() =>
  nodes.value
    .filter((node) => !focusNodeId.value || node.id === focusNodeId.value)
    .map((node) => ({
      ...node,
      values: Object.fromEntries(
        (latestMap.value[node.id]?.metrics || []).map((item) => [item.metric_key, item])
      ),
      ts: latestMap.value[node.id]?.metrics?.[0]?.ts
    }))
)

const compareOption = computed(() => {
  const palette = [chartC.value.primary, '#11A08F', '#DE8A1B', '#6B5BD2', '#D34848', '#23A06B']
  const series = []
  const labels = []
  compareNodes.value.forEach((nodeId, nodeIndex) => {
    selectedMetrics.value.forEach((metric, metricIndex) => {
      const points = seriesData.value[`${nodeId}:${metric}`] || []
      if (points.length && !labels.length) {
        points.forEach((point) => labels.push(fmtTime(point.ts).slice(5, 16)))
      }
      const node = nodes.value.find((item) => item.id === nodeId)
      const def = metricDefs.value.find((item) => item.metric_key === metric)
      series.push({
        name: `${node?.name || nodeId}${selectedMetrics.value.length > 1 ? ` · ${def?.name || metric}` : ''}`,
        type: 'line',
        smooth: true,
        symbol: 'none',
        data: points.map((point) => point.value),
        color: palette[(nodeIndex * 2 + metricIndex) % palette.length],
        lineStyle: { width: 2, color: palette[(nodeIndex * 2 + metricIndex) % palette.length] }
      })
    })
  })
  return {
    grid: { left: 56, right: 24, top: 34, bottom: 32 },
    tooltip: { trigger: 'axis' },
    legend: { top: 0, icon: 'roundRect', itemWidth: 10, itemHeight: 10, textStyle: { color: '#567792', fontSize: 11.5 }, type: 'scroll' },
    xAxis: {
      type: 'category', data: labels, boundaryGap: false,
      axisLine: { lineStyle: { color: '#DCE6F2' } },
      axisTick: { show: false },
      axisLabel: { color: '#8CA4BC', fontSize: 10.5, interval: Math.max(Math.floor(labels.length / 8), 0) }
    },
    yAxis: {
      type: 'value', scale: true,
      splitLine: { lineStyle: { color: '#EDF2F8' } },
      axisLabel: { color: '#8CA4BC', fontSize: 10.5 }
    },
    series
  }
})

const recentTelemetry = computed(() =>
  realtime.events.filter((item) => item.kind === '遥测').slice(0, 12)
)

function toggleCompare(id) {
  const index = compareNodes.value.indexOf(id)
  if (index >= 0) compareNodes.value.splice(index, 1)
  else compareNodes.value.push(id)
  loadSeries()
}
</script>

<template>
  <div>
    <!-- 控制栏 -->
    <div class="card mb-16">
      <div class="card-body tight">
        <div class="toolbar">
          <div class="row gap-8">
            <span class="small muted">监控节点</span>
            <select v-model="focusNodeId" class="select" style="width: 220px">
              <option :value="null">全部节点（{{ nodes.length }}）</option>
              <option v-for="node in nodes" :key="node.id" :value="node.id">{{ node.name }}</option>
            </select>
          </div>
          <div class="divider-v" />
          <div class="row gap-8">
            <span class="small muted">对比指标</span>
            <div ref="metricBox" class="msel" :class="{ open: metricOpen }">
              <button type="button" class="msel-trigger" @click="metricOpen = !metricOpen">
                <span class="msel-value">
                  <template v-if="selectedMetricDefs.length === 1">
                    {{ selectedMetricDefs[0].name }}<span v-if="selectedMetricDefs[0].unit" class="msel-unit">/{{ selectedMetricDefs[0].unit }}</span>
                  </template>
                  <template v-else-if="selectedMetricDefs.length > 1">
                    {{ selectedMetricDefs[0].name }}
                    <span class="msel-more">+{{ selectedMetricDefs.length - 1 }}</span>
                  </template>
                  <span v-else class="msel-placeholder">请选择指标</span>
                </span>
                <AppIcon name="chevron-down" :size="13" class="msel-caret" />
              </button>

              <div v-if="metricOpen" class="msel-panel">
                <div class="msel-panel-head">
                  <span class="tiny muted">已选 {{ selectedMetrics.length }} / {{ metricDefs.length }}</span>
                  <button type="button" class="msel-reset tiny" @click="clearMetrics">恢复默认</button>
                </div>
                <div class="msel-list">
                  <div
                    v-for="item in metricDefs"
                    :key="item.metric_key"
                    class="msel-item"
                    :class="{ on: selectedMetrics.includes(item.metric_key) }"
                    @click="toggleMetric(item.metric_key)"
                  >
                    <span class="msel-box"><AppIcon v-if="selectedMetrics.includes(item.metric_key)" name="check" :size="10" :stroke="2.6" /></span>
                    <span class="msel-name">{{ item.name }}</span>
                    <span v-if="item.unit" class="msel-unit">{{ item.unit }}</span>
                  </div>
                  <div v-if="!metricDefs.length" class="msel-empty tiny muted">暂无可用指标</div>
                </div>
              </div>
            </div>
          </div>
          <div class="row gap-6">
            <button
              v-for="hour in [1, 6, 24, 72]"
              :key="hour"
              class="btn btn-sm"
              :class="{ 'btn-primary': historyHours === hour }"
              @click="historyHours = hour; loadSeries()"
            >{{ hour }}h</button>
          </div>
          <div class="grow" />
          <span class="row gap-6 tiny muted">
            <i class="live-dot" :class="{ on: realtime.connected }" />
            {{ realtime.connected ? '实时更新中' : '实时通道未连接' }}
          </span>
          <button class="btn btn-sm" @click="loadAll"><AppIcon name="refresh" :size="14" />刷新</button>
        </div>
      </div>
    </div>

    <!-- 实时数据表 -->
    <div class="card mb-16">
      <div class="card-head">
        <div class="card-title"><i class="bar" />节点实时数据</div>
        <span class="muted small">共 {{ monitorRows.length }} 个节点 · 每 30 秒自动刷新</span>
      </div>
      <div class="card-body flush">
        <div class="table-wrap" style="min-width: 940px">
          <table class="tbl">
            <thead>
              <tr>
                <th style="width: 230px">节点</th>
                <th style="width: 96px">状态</th>
                <th v-for="metric in tableMetrics" :key="metric.key" style="text-align: right">
                  {{ metric.name }}<span v-if="metric.unit" class="tiny muted-2"> /{{ metric.unit }}</span>
                </th>
                <th style="width: 108px">更新于</th>
              </tr>
            </thead>
            <tbody>
              <tr v-if="loading && !monitorRows.length">
                <td :colspan="tableMetrics.length + 3"><div class="skeleton" style="height: 60px" /></td>
              </tr>
              <tr v-else-if="!monitorRows.length">
                <td :colspan="tableMetrics.length + 3">
                  <EmptyState icon="monitor" title="暂无可监控节点" description="请先在节点管理中接入边缘节点" />
                </td>
              </tr>
              <tr v-else v-for="row in monitorRows" :key="row.id">
                <td>
                  <router-link :to="`/nodes/${row.id}`" class="node-link">{{ row.name }}</router-link>
                  <div class="tiny muted-2 mono">{{ row.node_uid }}</div>
                </td>
                <td><StatusTag :status="row.status" /></td>
                <td v-for="metric in tableMetrics" :key="metric.key" class="num text-right">
                  <template v-if="row.values[metric.key]">
                    <span :class="{ stale: !realtime.connected }">
                      {{ row.values[metric.key].value_num ?? row.values[metric.key].value_str }}
                    </span>
                  </template>
                  <span v-else class="muted-2">—</span>
                </td>
                <td><span class="small muted">{{ relativeTime(row.ts) }}</span></td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>

    <div class="grid-2">
      <!-- 对比曲线 -->
      <div class="card">
        <div class="card-head">
          <div class="card-title"><i class="bar" />多节点对比曲线</div>
          <div class="row gap-6">
            <select
              class="select"
              style="width: 180px"
              @change="(event) => { if (event.target.value) toggleCompare(Number(event.target.value)); event.target.value = '' }"
            >
              <option value="">+ 添加对比节点</option>
              <option v-for="node in nodes.filter((n) => !compareNodes.includes(n.id))" :key="node.id" :value="node.id">
                {{ node.name }}
              </option>
            </select>
          </div>
        </div>
        <div class="card-body">
          <div v-if="!compareNodes.length" class="empty">
            <AppIcon name="monitor" :size="24" :stroke="1.4" />
            <span>请添加需要对比的节点</span>
          </div>
          <template v-else>
            <div class="chip-row mb-10">
              <span v-for="nodeId in compareNodes" :key="nodeId" class="chip">
                {{ nodes.find((n) => n.id === nodeId)?.name || nodeId }}
                <button @click="toggleCompare(nodeId)"><AppIcon name="close" :size="11" /></button>
              </span>
            </div>
            <EChart :option="compareOption" :height="300" :loading="loading" />
          </template>
        </div>
      </div>

      <!-- 实时数据流 -->
      <div class="card">
        <div class="card-head">
          <div class="card-title"><i class="bar" />实时上报流</div>
          <button class="btn btn-sm btn-ghost" @click="realtime.events = []">清空</button>
        </div>
        <div class="card-body tight">
          <EmptyState
            v-if="!recentTelemetry.length"
            icon="radio"
            title="等待数据上报"
            description="节点上报数据后会在此实时滚动显示，便于观察采集频率与数值"
          />
          <div v-else class="stream">
            <div v-for="item in recentTelemetry" :key="item.id" class="stream-row">
              <div class="stream-main">
                <span class="tag tag-primary">{{ item.payload?.node_name }}</span>
                <span class="tiny muted-2">上报 {{ item.payload?.count }} 条</span>
              </div>
              <div class="stream-values">
                <span v-for="(sample, key) in item.payload?.samples || {}" :key="key" class="val-chip mono">
                  {{ key }}={{ sample.value_num ?? sample.value_str }}
                </span>
              </div>
              <span class="tiny muted-2 mono">{{ fmtTime(item.at).slice(11) }}</span>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.toolbar { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }
.divider-v { width: 1px; height: 22px; background: var(--c-border); }
.live-dot { width: 7px; height: 7px; border-radius: 50%; background: #93A9BE; display: inline-block; }
.live-dot.on { background: #2FB27C; box-shadow: 0 0 6px rgba(47, 178, 124, 0.7); animation: blink 1.6s ease-in-out infinite; }
@keyframes blink { 0%, 100% { opacity: 1; } 50% { opacity: 0.35; } }
.node-link { font-weight: 500; }
.stale { opacity: 0.55; }

/* ---------- 对比指标：下拉多选面板 ---------- */
.msel { position: relative; flex-shrink: 0; }
.msel-trigger {
  display: inline-flex; align-items: center; gap: 8px;
  width: 232px; height: 34px; padding: 0 10px;
  background: var(--c-surface); border: 1px solid var(--c-border);
  border-radius: var(--radius); color: var(--c-text);
  font-size: 13px; font-family: inherit; cursor: pointer; text-align: left;
  transition: border-color .15s, box-shadow .15s;
}
.msel-trigger:hover { border-color: var(--c-primary-300); }
.msel.open .msel-trigger { border-color: var(--c-primary); box-shadow: 0 0 0 3px var(--c-primary-100); }
.msel-value {
  flex: 1; min-width: 0; display: flex; align-items: center; gap: 6px;
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.msel-placeholder { color: var(--c-text-3); }
.msel-unit { color: var(--c-text-3); font-size: 11.5px; flex-shrink: 0; }
.msel-more {
  flex-shrink: 0; padding: 0 6px; border-radius: 8px; font-size: 11px; line-height: 16px;
  background: var(--c-primary-100); color: var(--c-primary-600);
}
.msel-caret { color: var(--c-text-3); flex-shrink: 0; transition: transform .16s ease; }
.msel.open .msel-caret { transform: rotate(180deg); }

.msel-panel {
  position: absolute; z-index: 60; top: calc(100% + 6px); left: 0;
  width: 300px; background: var(--c-surface);
  border: 1px solid var(--c-border); border-radius: var(--radius-lg);
  box-shadow: var(--shadow-lg); overflow: hidden;
}
.msel-panel-head {
  display: flex; align-items: center; justify-content: space-between;
  padding: 8px 12px; background: var(--c-surface-2); border-bottom: 1px solid var(--c-border-soft);
}
.msel-reset {
  border: none; background: transparent; color: var(--c-primary-600);
  font-family: inherit; cursor: pointer; padding: 0;
}
.msel-reset:hover { text-decoration: underline; }
.msel-list { max-height: 264px; overflow-y: auto; padding: 6px; }
.msel-item {
  display: flex; align-items: center; gap: 8px;
  padding: 6px 8px; border-radius: var(--radius-sm);
  cursor: pointer; font-size: 13px; color: var(--c-text-2);
  transition: background .12s, color .12s;
}
.msel-item:hover { background: var(--c-surface-2); color: var(--c-text); }
.msel-item.on { background: var(--c-primary-50); color: var(--c-primary-700); font-weight: 500; }
.msel-box {
  width: 15px; height: 15px; flex-shrink: 0; border-radius: 4px;
  border: 1.5px solid var(--c-border-strong); background: var(--c-surface);
  display: inline-flex; align-items: center; justify-content: center;
  color: #fff; transition: background .12s, border-color .12s;
}
.msel-item.on .msel-box { background: var(--c-primary); border-color: var(--c-primary); }
.msel-name { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.msel-empty { padding: 14px 0; text-align: center; }

.chip-row { display: flex; gap: 6px; flex-wrap: wrap; }
.chip {
  display: inline-flex; align-items: center; gap: 5px;
  padding: 3px 6px 3px 10px; border-radius: 14px;
  background: var(--c-primary-100); color: var(--c-primary-600); font-size: 12px;
}
.chip button {
  border: none; background: transparent; color: var(--c-primary-600);
  cursor: pointer; display: flex; padding: 2px; border-radius: 50%;
}
.chip button:hover { background: rgba(29, 111, 184, 0.16); }

.stream { display: flex; flex-direction: column; max-height: 344px; overflow-y: auto; }
.stream-row {
  display: flex; align-items: center; gap: 10px;
  padding: 8px 6px; border-bottom: 1px solid #F1F6FB;
}
.stream-row:last-child { border-bottom: none; }
.stream-main { display: flex; align-items: center; gap: 7px; width: 190px; flex-shrink: 0; }
.stream-values { display: flex; gap: 6px; flex-wrap: wrap; flex: 1; }
.val-chip {
  padding: 1px 7px; border-radius: 5px; font-size: 11.5px;
  background: var(--c-surface-3); color: var(--c-text-2);
}
</style>
