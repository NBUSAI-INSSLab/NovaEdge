<script setup>
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api, fmtBytes, fmtDuration, fmtNumber, fmtTime, mediaUrl, relativeTime } from '@/api'
import { useChartColors } from '@/utils/chartPalette'
import { useRealtimeStore } from '@/stores/realtime'
import EChart from '@/components/EChart.vue'
import AppIcon from '@/components/AppIcon.vue'
import StatusTag from '@/components/StatusTag.vue'
import DataTable from '@/components/DataTable.vue'
import CommandDialog from '@/components/CommandDialog.vue'
import EmptyState from '@/components/EmptyState.vue'

const route = useRoute()
const chartC = useChartColors()
const router = useRouter()
const realtime = useRealtimeStore()

const nodeId = computed(() => Number(route.params.id))
const loading = ref(true)
const node = ref(null)
const statistics = ref(null)
const latest = ref(null)
const heartbeats = ref([])
const logs = ref([])
const logTotal = ref(0)
const logPage = ref(1)
const commandHistory = ref([])
const mediaFiles = ref([])
const showCommand = ref(false)
const activeTab = ref('telemetry')
const historyHours = ref(6)
const metricKeys = ref([])
const selectedMetric = ref('')
const series = ref({})

const nodeColumns = [
  { key: 'command_label', label: '指令', width: '130px' },
  { key: 'params', label: '参数', width: '190px' },
  { key: 'status', label: '状态', width: '100px' },
  { key: 'issued_by', label: '下发人', width: '110px' },
  { key: 'issued_at', label: '下发时间', width: '160px' },
  { key: 'result', label: '执行结果' }
]

const logColumns = [
  { key: 'level', label: '级别', width: '90px' },
  { key: 'module', label: '模块', width: '130px' },
  { key: 'message', label: '内容' },
  { key: 'created_at', label: '时间', width: '165px' }
]

async function loadNode() {
  const res = await api.nodes.detail(nodeId.value)
  if (res.code === 0) node.value = res.data
}

async function loadAll() {
  loading.value = true
  try {
    await loadNode()
    const [stat, lat, hb, lg, cmd, media] = await Promise.all([
      api.nodes.statistics(nodeId.value),
      api.nodes.latest(nodeId.value),
      api.nodes.heartbeats(nodeId.value, { hours: 1, limit: 240 }),
      api.nodes.logs(nodeId.value, { page: logPage.value, page_size: 15 }),
      api.commands.list({ node_id: nodeId.value, page: 1, page_size: 8 }),
      api.media.list({ node_id: nodeId.value, page: 1, page_size: 8 })
    ])
    if (stat.code === 0) statistics.value = stat.data
    if (lat.code === 0) {
      latest.value = lat.data
      metricKeys.value = (lat.data.metrics || []).map((item) => item.metric_key)
      if (!selectedMetric.value && metricKeys.value.length) selectedMetric.value = metricKeys.value[0]
    }
    if (hb.code === 0) heartbeats.value = hb.data
    if (lg.code === 0) { logs.value = lg.data.items; logTotal.value = lg.data.total }
    if (cmd.code === 0) commandHistory.value = cmd.data.items
    if (media.code === 0) mediaFiles.value = media.data.items
    await loadSeries()
  } finally {
    loading.value = false
  }
}

async function loadSeries() {
  if (!metricKeys.value.length) return
  const res = await api.nodes.telemetry(nodeId.value, {
    metric: selectedMetric.value || undefined,
    hours: historyHours.value,
    points: 500
  })
  if (res.code === 0) series.value = res.data
}

async function loadLogs() {
  const res = await api.nodes.logs(nodeId.value, { page: logPage.value, page_size: 15 })
  if (res.code === 0) { logs.value = res.data.items; logTotal.value = res.data.total }
}

onMounted(loadAll)

// 该节点的遥测实时推送 -> 局部刷新指标与曲线
const unregister = () => {}
onUnmounted(unregister)

/* ------------------------------- 图表 ------------------------------- */
const resourceOption = computed(() => {
  const labels = heartbeats.value.map((item) => fmtTime(item.created_at).slice(11))
  return {
    grid: { left: 42, right: 42, top: 30, bottom: 26 },
    tooltip: { trigger: 'axis' },
    legend: { top: 0, icon: 'roundRect', itemWidth: 10, itemHeight: 10, textStyle: { color: '#567792', fontSize: 11.5 } },
    xAxis: {
      type: 'category', data: labels, boundaryGap: false,
      axisLine: { lineStyle: { color: '#DCE6F2' } },
      axisLabel: { color: '#8CA4BC', fontSize: 10.5, interval: Math.max(Math.floor(labels.length / 7), 0) },
      axisTick: { show: false }
    },
    yAxis: [
      { type: 'value', name: '%', max: 100, nameTextStyle: { color: '#8CA4BC', fontSize: 11 }, splitLine: { lineStyle: { color: '#EDF2F8' } }, axisLabel: { color: '#8CA4BC', fontSize: 10.5 } },
      { type: 'value', name: '℃', nameTextStyle: { color: '#8CA4BC', fontSize: 11 }, splitLine: { show: false }, axisLabel: { color: '#8CA4BC', fontSize: 10.5 } }
    ],
    series: [
      { name: 'CPU', type: 'line', smooth: true, symbol: 'none', data: heartbeats.value.map((i) => i.cpu_percent), lineStyle: { width: 2, color: chartC.value.primary } },
      { name: '内存', type: 'line', smooth: true, symbol: 'none', data: heartbeats.value.map((i) => i.mem_percent), lineStyle: { width: 2, color: '#11A08F' } },
      { name: '磁盘', type: 'line', smooth: true, symbol: 'none', data: heartbeats.value.map((i) => i.disk_percent), lineStyle: { width: 1.6, color: '#93A9BE', type: 'dashed' } },
      { name: 'SoC 温度', type: 'line', yAxisIndex: 1, smooth: true, symbol: 'none', data: heartbeats.value.map((i) => i.cpu_temp), lineStyle: { width: 2, color: '#DE8A1B' } }
    ]
  }
})

const metricOption = computed(() => {
  const allPoints = Object.values(series.value).flat()
  const points = (series.value[selectedMetric.value] || []).length
    ? series.value[selectedMetric.value]
    : (Object.values(series.value)[0] || [])
  const defs = Object.fromEntries((latest.value?.metrics || []).map((m) => [m.metric_key, m]))
  const meta = defs[selectedMetric.value] || {}
  return {
    grid: { left: 52, right: 24, top: 30, bottom: 32 },
    tooltip: {
      trigger: 'axis',
      formatter: (params) => {
        const item = params[0]
        if (!item) return ''
        return `${fmtTime(item.value[0])}<br/>${meta.name || selectedMetric.value}：<b>${item.value[1]}</b> ${meta.unit || ''}`
      }
    },
    xAxis: {
      type: 'category',
      data: points.map((item) => fmtTime(item.ts).slice(5, 16)),
      boundaryGap: false,
      axisLine: { lineStyle: { color: '#DCE6F2' } },
      axisLabel: { color: '#8CA4BC', fontSize: 10.5, interval: Math.max(Math.floor(points.length / 8), 0) },
      axisTick: { show: false }
    },
    yAxis: {
      type: 'value',
      name: meta.unit || '',
      scale: true,
      nameTextStyle: { color: '#8CA4BC', fontSize: 11 },
      splitLine: { lineStyle: { color: '#EDF2F8' } },
      axisLabel: { color: '#8CA4BC', fontSize: 10.5 }
    },
    series: [{
      type: 'line',
      smooth: true,
      symbol: 'none',
      data: points.map((item) => item.value),
      lineStyle: { width: 2.2, color: chartC.value.primary },
      areaStyle: {
        color: {
          type: 'linear', x: 0, y: 0, x2: 0, y2: 1,
          colorStops: [{ offset: 0, color: 'rgba(29,111,184,0.26)' }, { offset: 1, color: 'rgba(29,111,184,0.02)' }]
        }
      }
    }]
  }
})

function gaugeOption(label, value, unit, color, max = 100) {
  return {
    series: [{
      type: 'gauge',
      startAngle: 210, endAngle: -30,
      min: 0, max,
      radius: '96%',
      center: ['50%', '58%'],
      progress: { show: true, width: 9, roundCap: true, itemStyle: { color } },
      axisLine: { lineStyle: { width: 9, color: [[1, '#EAF0F7']] } },
      pointer: { show: false },
      axisTick: { show: false },
      splitLine: { show: false },
      axisLabel: { show: false },
      detail: {
        valueAnimation: true,
        offsetCenter: [0, '-6%'],
        formatter: `{value}${unit}`,
        fontSize: 17, fontWeight: 600, color: '#14283D'
      },
      title: { offsetCenter: [0, '26%'], fontSize: 11.5, color: '#8CA4BC' },
      data: [{ value: Number(value || 0).toFixed(1), name: label }]
    }]
  }
}

const cpuGauge = computed(() => gaugeOption('CPU 使用率', latest.value?.resource.cpu_percent, '%', chartC.value.primary))
const memGauge = computed(() => gaugeOption('内存使用率', latest.value?.resource.mem_percent, '%', '#11A08F'))
const tempGauge = computed(() => gaugeOption('SoC 温度', latest.value?.resource.cpu_temp, '℃', '#DE8A1B', 100))
const diskGauge = computed(() => gaugeOption('磁盘使用率', latest.value?.resource.disk_percent, '%', '#6B5BD2'))

const statusTone = { critical: 'tag-critical', major: 'tag-major', minor: 'tag-minor', warning: 'tag-warning' }
const cmdStatusTone = { success: 'tag-online', failed: 'tag-critical', timeout: 'tag-major', sent: 'tag-warning', pending: 'tag-primary' }

function metricTone(metric) {
  const def = (latest.value?.metrics || []).find((m) => m.metric_key === metric.metric_key)
  return def ? 'tag-primary' : 'tag'
}

function prettyParams(params) {
  if (!params || !Object.keys(params).length) return '—'
  return Object.entries(params).map(([k, v]) => `${k}=${v}`).join(', ')
}
</script>

<template>
  <div>
    <!-- 面包屑 -->
    <div class="crumb">
      <router-link to="/nodes" class="crumb-link"><AppIcon name="arrow-left" :size="14" />返回节点列表</router-link>
      <span class="muted-2">/</span>
      <span>{{ node?.name || '节点详情' }}</span>
    </div>

    <!-- 基本信息 -->
    <div class="card mb-16">
      <div class="card-body">
        <div v-if="loading && !node" class="skeleton" style="height: 92px" />
        <div v-else-if="node" class="node-head">
          <div class="node-head-left">
            <div class="node-avatar">
              <AppIcon :name="node.node_type === 'generic' ? 'server' : 'cpu'" :size="24" />
            </div>
            <div>
              <div class="row gap-10">
                <h2 class="node-title">{{ node.name }}</h2>
                <StatusTag :status="node.status" :label="node.status_label" />
                <span class="tag tag-primary">{{ node.node_type_label }}</span>
              </div>
              <div class="node-sub">
                <span class="mono">{{ node.node_uid }}</span>
                <span class="dot-sep" />
                <span>{{ node.group_name }}</span>
                <span class="dot-sep" />
                <span><AppIcon name="map-pin" :size="12" /> {{ node.location || '未设置位置' }}</span>
                <span class="dot-sep" />
                <span class="mono">{{ node.ip_address || '未上报 IP' }}</span>
              </div>
            </div>
          </div>
          <div class="node-head-right">
            <div class="kv"><span>最后在线</span><strong>{{ relativeTime(node.last_seen_at) }}</strong></div>
            <div class="kv"><span>已运行</span><strong>{{ fmtDuration(node.uptime_seconds) }}</strong></div>
            <div class="kv"><span>上报周期</span><strong>{{ node.report_interval }} 秒</strong></div>
            <button v-if="node" class="btn btn-primary btn-sm" @click="showCommand = true">
              <AppIcon name="command" :size="14" />下发指令
            </button>
          </div>
        </div>
      </div>
    </div>

    <!-- 统计卡 -->
    <div class="grid-4 mb-16">
      <div class="mini-stat">
        <AppIcon name="activity" :size="18" />
        <div><div class="mini-label">遥测数据点</div><div class="mini-value">{{ fmtNumber(statistics?.total_points) }}</div></div>
      </div>
      <div class="mini-stat">
        <AppIcon name="metric" :size="18" />
        <div><div class="mini-label">采集指标数</div><div class="mini-value">{{ statistics?.metric_count ?? 0 }}</div></div>
      </div>
      <div class="mini-stat">
        <AppIcon name="media" :size="18" />
        <div>
          <div class="mini-label">媒体文件</div>
          <div class="mini-value">{{ statistics?.media_count ?? 0 }}
            <em>（图 {{ statistics?.image_count ?? 0 }} / 视频 {{ statistics?.video_count ?? 0 }}）</em>
          </div>
        </div>
      </div>
      <div class="mini-stat">
        <AppIcon name="hard-drive" :size="18" />
        <div><div class="mini-label">媒体占用</div><div class="mini-value">{{ fmtBytes(statistics?.storage_bytes) }}</div></div>
      </div>
    </div>

    <!-- 资源仪表 -->
    <div class="grid-4 mb-16">
      <div class="card"><div class="card-body" style="padding: 8px 10px 12px"><EChart :option="cpuGauge" :height="158" /></div></div>
      <div class="card"><div class="card-body" style="padding: 8px 10px 12px"><EChart :option="memGauge" :height="158" /></div></div>
      <div class="card"><div class="card-body" style="padding: 8px 10px 12px"><EChart :option="tempGauge" :height="158" /></div></div>
      <div class="card"><div class="card-body" style="padding: 8px 10px 12px"><EChart :option="diskGauge" :height="158" /></div></div>
    </div>

    <!-- Tab 区 -->
    <div class="card">
      <div class="card-head">
        <div class="tabs">
          <button
            v-for="tab in [
              { key: 'telemetry', label: '实时数据' },
              { key: 'resource', label: '资源曲线' },
              { key: 'media', label: '媒体文件' },
              { key: 'commands', label: '指令历史' },
              { key: 'logs', label: '运行日志' }
            ]"
            :key="tab.key"
            class="tab"
            :class="{ active: activeTab === tab.key }"
            @click="activeTab = tab.key"
          >{{ tab.label }}</button>
        </div>
        <div class="row gap-8">
          <button class="btn btn-sm" @click="loadAll"><AppIcon name="refresh" :size="14" />刷新</button>
        </div>
      </div>

      <div class="card-body">
        <!-- 实时数据 -->
        <div v-if="activeTab === 'telemetry'">
          <div v-if="!latest?.metrics?.length">
            <EmptyState icon="activity" title="暂无遥测数据" description="节点尚未上报传感器数据，请检查节点 Agent 运行状态" />
          </div>
          <div v-else>
            <div class="metric-cards">
              <div v-for="item in latest.metrics" :key="item.metric_key" class="metric-card">
                <div class="metric-top">
                  <span class="metric-name">{{ item.name }}</span>
                  <span class="tag tag-primary">{{ item.category === 'system' ? '系统' : '采集' }}</span>
                </div>
                <div class="metric-value">
                  {{ item.value_num ?? item.value_str }}
                  <em v-if="item.unit">{{ item.unit }}</em>
                </div>
                <div class="metric-foot">
                  <span class="mono tiny">{{ item.metric_key }}</span>
                  <span class="tiny muted-2">{{ relativeTime(item.ts) }}</span>
                </div>
              </div>
            </div>

            <div class="row-between mt-16 mb-10">
              <div class="row gap-8">
                <span class="small muted">指标曲线：</span>
                <select v-model="selectedMetric" class="select" style="width: 190px" @change="loadSeries">
                  <option v-for="key in metricKeys" :key="key" :value="key">
                    {{ (latest.metrics.find((m) => m.metric_key === key) || {}).name || key }}
                  </option>
                </select>
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
            </div>
            <EChart :option="metricOption" :height="300" :loading="loading" />
          </div>
        </div>

        <!-- 资源曲线 -->
        <div v-else-if="activeTab === 'resource'">
          <EChart :option="resourceOption" :height="320" :loading="loading" />
          <div class="grid-4 mt-16">
            <div class="kv-card"><span>上行速率</span><strong>{{ (heartbeats.at(-1)?.net_tx_kbps ?? 0).toFixed(1) }} kbps</strong></div>
            <div class="kv-card"><span>下行速率</span><strong>{{ (heartbeats.at(-1)?.net_rx_kbps ?? 0).toFixed(1) }} kbps</strong></div>
            <div class="kv-card"><span>进程数</span><strong>{{ heartbeats.at(-1)?.process_count ?? 0 }}</strong></div>
            <div class="kv-card"><span>心跳采样</span><strong>{{ heartbeats.length }} 条（近 1 小时）</strong></div>
          </div>
        </div>

        <!-- 媒体 -->
        <div v-else-if="activeTab === 'media'">
          <EmptyState
            v-if="!mediaFiles.length"
            icon="media"
            title="该节点暂无媒体文件"
            description="可下发「抓拍图片」或「开始录像」指令，节点执行后会自动上传并在此展示"
          />
          <div v-else class="media-grid">
            <router-link v-for="item in mediaFiles" :key="item.id" class="media-item" :to="`/media?preview=${item.id}`">
              <div class="media-box">
                <img v-if="item.file_type === 'image'" :src="mediaUrl(item.thumb_url || item.url)" :alt="item.file_name" loading="lazy" />
                <div v-else class="video-ph"><AppIcon name="play-circle" :size="26" /></div>
              </div>
              <div class="media-meta">
                <div class="ellipsis tiny">{{ item.file_name }}</div>
                <div class="tiny muted-2">{{ item.file_size_human }} · {{ fmtTime(item.captured_at, false) }}</div>
              </div>
            </router-link>
          </div>
        </div>

        <!-- 指令历史 -->
        <div v-else-if="activeTab === 'commands'">
          <DataTable :columns="nodeColumns" :rows="commandHistory" :total="0" min-width="900px" empty-text="该节点暂无指令记录">
            <template #cell-params="{ row }"><span class="mono tiny">{{ prettyParams(row.params) }}</span></template>
            <template #cell-status="{ row }">
              <span class="tag" :class="cmdStatusTone[row.status] || 'tag'">{{ row.status_label }}</span>
            </template>
            <template #cell-issued_at="{ row }"><span class="small mono">{{ fmtTime(row.issued_at) }}</span></template>
            <template #cell-result="{ row }">
              <span class="tiny muted mono ellipsis" :title="JSON.stringify(row.result)">{{ JSON.stringify(row.result || {}) }}</span>
            </template>
          </DataTable>
        </div>

        <!-- 日志 -->
        <div v-else-if="activeTab === 'logs'">
          <DataTable
            v-model:page="logPage"
            :columns="logColumns"
            :rows="logs"
            :total="logTotal"
            :page-size="15"
            min-width="820px"
            empty-text="暂无节点日志上报"
            @update:page="loadLogs"
          >
            <template #cell-level="{ row }">
              <span class="tag" :class="row.level === 'error' ? 'tag-critical' : row.level === 'warn' ? 'tag-major' : 'tag-primary'">
                {{ row.level }}
              </span>
            </template>
            <template #cell-message="{ row }"><span class="small">{{ row.message }}</span></template>
            <template #cell-created_at="{ row }"><span class="small mono">{{ fmtTime(row.created_at) }}</span></template>
          </DataTable>
        </div>
      </div>
    </div>

    <CommandDialog v-model="showCommand" :nodes="node ? [node] : []" @issued="loadAll" />
  </div>
</template>

<style scoped>
.crumb { display: flex; align-items: center; gap: 9px; margin-bottom: 14px; font-size: 13px; }
.crumb-link { display: flex; align-items: center; gap: 5px; color: var(--c-text-2); }
.crumb-link:hover { color: var(--c-primary); }

.node-head { display: flex; align-items: center; justify-content: space-between; gap: 20px; flex-wrap: wrap; }
.node-head-left { display: flex; align-items: center; gap: 14px; }
.node-avatar {
  width: 52px; height: 52px; border-radius: 14px;
  display: flex; align-items: center; justify-content: center;
  background: linear-gradient(135deg, var(--c-primary-100), #CFE4F7);
  color: var(--c-primary-600);
}
.node-title { margin: 0; font-size: 19px; font-weight: 600; }
.node-sub { display: flex; align-items: center; gap: 9px; margin-top: 5px; font-size: 12.5px; color: var(--c-text-2); flex-wrap: wrap; }
.node-sub span { display: flex; align-items: center; gap: 4px; }
.dot-sep { width: 3px; height: 3px; border-radius: 50%; background: var(--c-border-strong); }
.node-head-right { display: flex; align-items: center; gap: 22px; flex-wrap: wrap; }
.kv { display: flex; flex-direction: column; }
.kv span { font-size: 11.5px; color: var(--c-text-3); }
.kv strong { font-size: 13.5px; font-weight: 600; }

.mini-stat {
  display: flex; align-items: center; gap: 12px;
  padding: 14px 16px; background: var(--c-surface);
  border: 1px solid var(--c-border); border-radius: var(--radius-lg);
  color: var(--c-primary);
}
.mini-label { font-size: 12px; color: var(--c-text-3); }
.mini-value { font-size: 17px; font-weight: 600; color: var(--c-text); }
.mini-value em { font-size: 11.5px; font-style: normal; color: var(--c-text-3); font-weight: 500; }

.tabs { display: flex; gap: 4px; }
.tab {
  height: 32px; padding: 0 14px; border: none; border-radius: 8px;
  background: transparent; color: var(--c-text-2);
  font-family: inherit; font-size: 13px; cursor: pointer; transition: all 0.16s;
}
.tab:hover { background: var(--c-surface-3); color: var(--c-primary); }
.tab.active { background: var(--c-primary-100); color: var(--c-primary-600); font-weight: 600; }

.metric-cards { display: grid; grid-template-columns: repeat(auto-fill, minmax(190px, 1fr)); gap: 12px; }
.metric-card {
  padding: 13px 15px; border-radius: 11px;
  background: var(--c-surface-2); border: 1px solid var(--c-border);
}
.metric-top { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
.metric-name { font-size: 12.5px; color: var(--c-text-2); }
.metric-value { font-size: 23px; font-weight: 600; margin: 5px 0 3px; font-variant-numeric: tabular-nums; }
.metric-value em { font-size: 12px; font-style: normal; color: var(--c-text-3); font-weight: 500; margin-left: 3px; }
.metric-foot { display: flex; align-items: center; justify-content: space-between; gap: 8px; }

.kv-card {
  display: flex; flex-direction: column; gap: 3px;
  padding: 12px 14px; border-radius: 10px;
  background: var(--c-surface-2); border: 1px solid var(--c-border);
}
.kv-card span { font-size: 11.5px; color: var(--c-text-3); }
.kv-card strong { font-size: 14px; }

.media-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(160px, 1fr)); gap: 12px; }
.media-item { border: 1px solid var(--c-border); border-radius: 10px; overflow: hidden; }
.media-item:hover { border-color: var(--c-primary-300); box-shadow: var(--shadow-sm); }
.media-box { aspect-ratio: 4 / 3; background: var(--c-surface-3); overflow: hidden; }
.media-box img { width: 100%; height: 100%; object-fit: cover; display: block; }
.video-ph { width: 100%; height: 100%; display: flex; align-items: center; justify-content: center; background: linear-gradient(135deg, #1A3F63, #0E2B47); color: #7FE3D0; }
.media-meta { padding: 6px 9px 8px; }
</style>
