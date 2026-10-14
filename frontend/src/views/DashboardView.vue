<script setup>
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { api, fmtNumber, fmtTime, mediaUrl, relativeTime } from '@/api'
import { useRealtimeStore } from '@/stores/realtime'
import { useChartColors, hexToRgba } from '@/utils/chartPalette'
import StatCard from '@/components/StatCard.vue'
import EChart from '@/components/EChart.vue'
import AppIcon from '@/components/AppIcon.vue'
import StatusTag from '@/components/StatusTag.vue'
import EmptyState from '@/components/EmptyState.vue'

const realtime = useRealtimeStore()
const chartC = useChartColors()

const loading = ref(true)
const overview = ref(null)
const distribution = ref({ by_status: [], by_type: [], by_group: [] })
const trend = ref({ labels: [], points: [], media: [] })
const topNodes = ref({ by_points: [], by_media: [] })
const metricRanking = ref([])
const recent = ref({ alerts: [], media: [], commands: [] })
const trendHours = ref(24)

async function loadAll() {
  loading.value = true
  try {
    const [ov, dist, tr, top, ranking, rec] = await Promise.all([
      api.dashboard.overview(),
      api.dashboard.distribution(),
      api.dashboard.trend(trendHours.value),
      api.dashboard.topNodes(6),
      api.dashboard.metricRanking(8),
      api.dashboard.recent(6)
    ])
    if (ov.code === 0) overview.value = ov.data
    if (dist.code === 0) distribution.value = dist.data
    if (tr.code === 0) trend.value = tr.data
    if (top.code === 0) topNodes.value = top.data
    if (ranking.code === 0) metricRanking.value = ranking.data
    if (rec.code === 0) recent.value = rec.data
  } finally {
    loading.value = false
  }
}

async function reloadTrend() {
  const res = await api.dashboard.trend(trendHours.value)
  if (res.code === 0) trend.value = res.data
}

onMounted(loadAll)
let timer = setInterval(() => {
  api.dashboard.overview().then((res) => { if (res.code === 0) overview.value = res.data })
}, 20000)
onUnmounted(() => clearInterval(timer))

/* ------------------------------- 图表配置 ------------------------------- */
const palette = computed(() => [chartC.value.primary, '#11A08F', '#6B5BD2', '#DE8A1B', '#D34848', '#23A06B'])

const statusOption = computed(() => ({
  tooltip: { trigger: 'item', formatter: '{b}: {c} 个 ({d}%)' },
  legend: { bottom: 0, icon: 'circle', itemWidth: 8, itemHeight: 8, textStyle: { color: chartC.value.text2, fontSize: 12 } },
  series: [{
    type: 'pie',
    radius: ['52%', '74%'],
    center: ['50%', '44%'],
    avoidLabelOverlap: true,
    itemStyle: { borderColor: '#fff', borderWidth: 2, borderRadius: 4 },
    label: { show: false },
    data: (distribution.value.by_status || []).map((item, index) => ({
      name: item.name,
      value: item.value,
      itemStyle: {
        color: item.key === 'online' ? '#23A06B' : item.key === 'offline' ? '#93A9BE' : '#DE8A1B'
      }
    }))
  }],
  graphic: overview.value ? [{
    type: 'text',
    left: 'center',
    top: '38%',
    style: {
      text: `${overview.value.nodes.online_rate}%`,
      fontSize: 22,
      fontWeight: 600,
      fill: chartC.value.text,
      textAlign: 'center'
    }
  }, {
    type: 'text',
    left: 'center',
    top: '52%',
    style: { text: '在线率', fontSize: 11.5, fill: chartC.value.text3, textAlign: 'center' }
  }] : []
}))

const trendOption = computed(() => ({
  grid: { left: 48, right: 24, top: 32, bottom: 30 },
  tooltip: { trigger: 'axis', axisPointer: { type: 'cross', label: { backgroundColor: chartC.value.primary } } },
  legend: { top: 0, right: 0, icon: 'roundRect', itemWidth: 10, itemHeight: 10, textStyle: { color: chartC.value.text2, fontSize: 12 } },
  xAxis: {
    type: 'category',
    data: trend.value.labels,
    boundaryGap: false,
    axisLine: { lineStyle: { color: chartC.value.border } },
    axisLabel: { color: chartC.value.text3, fontSize: 11, interval: Math.max(Math.floor(trend.value.labels.length / 8), 0) },
    axisTick: { show: false }
  },
  yAxis: {
    type: 'value',
    name: '数据点',
    nameTextStyle: { color: chartC.value.text3, fontSize: 11 },
    splitLine: { lineStyle: { color: chartC.value.borderSoft } },
    axisLabel: { color: chartC.value.text3, fontSize: 11 }
  },
  series: [
    {
      name: '遥测数据点',
      type: 'line',
      smooth: true,
      symbol: 'none',
      data: trend.value.points,
      color: chartC.value.primary,
      lineStyle: { width: 2.4, color: chartC.value.primary },
      areaStyle: {
        color: {
          type: 'linear', x: 0, y: 0, x2: 0, y2: 1,
          colorStops: [
            { offset: 0, color: hexToRgba(chartC.value.primary, 0.30) },
            { offset: 1, color: hexToRgba(chartC.value.primary, 0.02) }
          ]
        }
      }
    },
    {
      name: '媒体上传',
      type: 'line',
      smooth: true,
      symbol: 'none',
      data: trend.value.media,
      color: '#11A08F',
      lineStyle: { width: 2, color: '#11A08F' }
    }
  ]
}))

const typeOption = computed(() => ({
  grid: { left: 82, right: 26, top: 12, bottom: 12 },
  tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
  xAxis: { type: 'value', splitLine: { lineStyle: { color: chartC.value.borderSoft } }, axisLabel: { color: chartC.value.text3, fontSize: 11 } },
  yAxis: {
    type: 'category',
    data: (distribution.value.by_type || []).map((item) => item.name),
    axisLine: { show: false },
    axisTick: { show: false },
    axisLabel: { color: chartC.value.text2, fontSize: 12 }
  },
  series: [{
    type: 'bar',
    barWidth: 14,
    data: (distribution.value.by_type || []).map((item, index) => ({
      value: item.value,
      itemStyle: { color: palette.value[index % palette.value.length], borderRadius: [0, 4, 4, 0] }
    })),
    label: { show: true, position: 'right', color: chartC.value.text2, fontSize: 11.5 }
  }]
}))

const rankingOption = computed(() => ({
  grid: { left: 96, right: 52, top: 10, bottom: 10 },
  tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
  xAxis: { type: 'value', splitLine: { lineStyle: { color: chartC.value.borderSoft } }, axisLabel: { color: chartC.value.text3, fontSize: 11 } },
  yAxis: {
    type: 'category',
    data: metricRanking.value.map((item) => item.name).reverse(),
    axisLine: { show: false },
    axisTick: { show: false },
    axisLabel: { color: chartC.value.text2, fontSize: 11.5 }
  },
  series: [{
    type: 'bar',
    barWidth: 13,
    data: metricRanking.value.map((item) => item.value).reverse(),
    itemStyle: {
      borderRadius: [0, 4, 4, 0],
      color: {
        type: 'linear', x: 0, y: 0, x2: 1, y2: 0,
        colorStops: [{ offset: 0, color: chartC.value.primary300 }, { offset: 1, color: chartC.value.primary }]
      }
    },
    label: { show: true, position: 'right', color: chartC.value.text2, fontSize: 11, formatter: (p) => fmtNumber(p.value) }
  }]
}))

const severityTone = { critical: 'tag-critical', major: 'tag-major', minor: 'tag-minor', warning: 'tag-warning' }
</script>

<template>
  <div class="dashboard">
    <!-- 指标卡 -->
    <div class="grid-4">
      <StatCard
        label="接入节点"
        :value="overview ? overview.nodes.total : '—'"
        unit="个"
        icon="node"
        tone="primary"
        :loading="loading"
        :hint="overview ? `在线 ${overview.nodes.online} · 离线 ${overview.nodes.offline} · 在线率 ${overview.nodes.online_rate}%` : ''"
      />
      <StatCard
        label="今日数据点"
        :value="overview ? fmtNumber(overview.data.today_points) : '—'"
        unit="条"
        icon="activity"
        tone="teal"
        :loading="loading"
        :hint="overview ? `累计 ${fmtNumber(overview.data.total_points)} 条 · ${overview.data.metric_defs} 个指标` : ''"
      />
      <StatCard
        label="数据资产"
        :value="overview ? overview.media.total : '—'"
        unit="个"
        icon="media"
        tone="purple"
        :loading="loading"
        :hint="overview ? `图片 ${overview.media.images} · 视频 ${overview.media.videos} · 今日新增 ${overview.media.today}` : ''"
      />
      <StatCard
        label="存储占用"
        :value="overview ? overview.media.storage_human : '—'"
        icon="hard-drive"
        tone="amber"
        :loading="loading"
        hint="图片与视频原始文件"
      />
    </div>

    <div class="grid-4 mt-16">
      <StatCard
        label="活跃告警"
        :value="overview ? overview.alerts.active : '—'"
        unit="条"
        icon="alert"
        :tone="overview && overview.alerts.active > 0 ? 'red' : 'green'"
        :loading="loading"
        :hint="overview ? `今日新增 ${overview.alerts.today} 条` : ''"
      />
      <StatCard
        label="平均 CPU"
        :value="overview ? overview.resource.avg_cpu : '—'"
        unit="%"
        icon="cpu"
        tone="primary"
        :loading="loading"
      />
      <StatCard
        label="平均内存"
        :value="overview ? overview.resource.avg_mem : '—'"
        unit="%"
        icon="server"
        tone="teal"
        :loading="loading"
      />
      <StatCard
        label="平均 SoC 温度"
        :value="overview ? overview.resource.avg_temp : '—'"
        unit="℃"
        icon="thermometer"
        :tone="overview && overview.resource.avg_temp > 70 ? 'red' : 'green'"
        :loading="loading"
      />
    </div>

    <!-- 趋势 + 分布 -->
    <div class="grid-2 mt-16">
      <div class="card">
        <div class="card-head">
          <div class="card-title"><i class="bar" />数据上报趋势</div>
          <div class="row gap-6">
            <button
              v-for="hour in [6, 24, 72]"
              :key="hour"
              class="btn btn-sm"
              :class="{ 'btn-primary': trendHours === hour }"
              @click="trendHours = hour; reloadTrend()"
            >{{ hour }} 小时</button>
          </div>
        </div>
        <div class="card-body">
          <EChart :option="trendOption" :height="272" :loading="loading" />
        </div>
      </div>

      <div class="card">
        <div class="card-head">
          <div class="card-title"><i class="bar" />节点状态分布</div>
          <span class="tag tag-primary">{{ overview ? overview.nodes.groups : 0 }} 个分组</span>
        </div>
        <div class="card-body">
          <EChart :option="statusOption" :height="272" :loading="loading" />
        </div>
      </div>
    </div>

    <div class="grid-2 mt-16">
      <div class="card">
        <div class="card-head">
          <div class="card-title"><i class="bar" />节点类型构成</div>
        </div>
        <div class="card-body">
          <EChart :option="typeOption" :height="220" :loading="loading" />
        </div>
      </div>
      <div class="card">
        <div class="card-head">
          <div class="card-title"><i class="bar" />指标采样量排行</div>
          <span class="muted small">数据构成分析</span>
        </div>
        <div class="card-body">
          <EChart :option="rankingOption" :height="220" :loading="loading" />
        </div>
      </div>
    </div>

    <!-- 实时 + 媒体 -->
    <div class="grid-2 mt-16">
      <div class="card">
        <div class="card-head">
          <div class="card-title"><i class="bar" />实时事件流</div>
          <span class="row gap-6 tiny muted">
            <i class="live-dot" :class="{ on: realtime.connected }" />
            {{ realtime.connected ? '已连接' : '未连接' }}
          </span>
        </div>
        <div class="card-body tight">
          <div v-if="!realtime.events.length" class="empty" style="padding: 36px 12px">
            <AppIcon name="radio" :size="24" :stroke="1.4" />
            <span>等待节点上报事件</span>
          </div>
          <div v-else class="event-feed">
            <div v-for="item in realtime.events.slice(0, 8)" :key="item.id" class="feed-row">
              <span class="tag" :class="{
                'tag-primary': item.kind === '遥测',
                'tag-teal': ['节点', '心跳'].includes(item.kind),
                'tag-critical': item.level === 'error',
                'tag-major': item.level === 'warning',
                'tag-online': item.level === 'success'
              }">{{ item.kind }}</span>
              <span class="grow ellipsis small">
                {{ ['节点', '心跳'].includes(item.kind) ? item.payload?.node?.name : '' }}
                {{ item.payload?.alert?.title || item.payload?.title || '' }}
                {{ item.kind === '遥测' ? `上报 ${item.payload?.count} 条数据` : '' }}
                {{ item.kind === '媒体' ? `${item.payload?.media?.file_type_label} ${item.payload?.media?.file_name}` : '' }}
                {{ item.kind === '指令' ? `${item.payload?.command?.command_label} ${item.payload?.command?.status_label}` : '' }}
                {{ item.kind === '日志' ? `上报 ${item.payload?.count} 条日志` : '' }}
              </span>
              <span class="tiny muted-2 mono">{{ fmtTime(item.at).slice(11) }}</span>
            </div>
          </div>
        </div>
      </div>

      <div class="card">
        <div class="card-head">
          <div class="card-title"><i class="bar" />最新媒体上传</div>
          <router-link class="btn btn-sm" to="/media">查看全部</router-link>
        </div>
        <div class="card-body tight">
          <div v-if="!recent.media.length" class="empty" style="padding: 36px 12px">
            <AppIcon name="media" :size="24" :stroke="1.4" />
            <span>暂无媒体文件</span>
          </div>
          <div v-else class="media-grid">
            <router-link
              v-for="item in recent.media.slice(0, 6)"
              :key="item.id"
              class="media-thumb"
              :to="`/media?preview=${item.id}`"
            >
              <div class="thumb-box">
                <img v-if="item.file_type === 'image'" :src="mediaUrl(item.thumb_url || item.url)" :alt="item.file_name" loading="lazy" />
                <div v-else class="video-ph">
                  <AppIcon name="play-circle" :size="24" :stroke="1.5" />
                </div>
                <span class="type-chip">{{ item.file_type_label }}</span>
              </div>
              <div class="thumb-meta">
                <div class="ellipsis tiny">{{ item.file_name }}</div>
                <div class="tiny muted-2">{{ item.node_name }} · {{ item.file_size_human }}</div>
              </div>
            </router-link>
          </div>
        </div>
      </div>
    </div>

    <!-- 排行 + 告警 -->
    <div class="grid-2 mt-16" style="margin-bottom: 8px">
      <div class="card">
        <div class="card-head">
          <div class="card-title"><i class="bar" />节点数据量排行</div>
          <router-link class="btn btn-sm" to="/nodes">节点管理</router-link>
        </div>
        <div class="card-body flush">
          <div v-if="!topNodes.by_points.length" class="empty">
            <AppIcon name="bar-chart" :size="24" :stroke="1.4" />
            <span>暂无数据</span>
          </div>
          <table v-else class="tbl">
            <thead>
              <tr><th style="width: 44px">#</th><th>节点</th><th>状态</th><th style="text-align: right">遥测数据点</th></tr>
            </thead>
            <tbody>
              <tr v-for="(item, index) in topNodes.by_points" :key="item.node_id">
                <td>
                  <span class="rank" :class="{ top: index < 3 }">{{ index + 1 }}</span>
                </td>
                <td>
                  <router-link :to="`/nodes/${item.node_id}`" class="node-link">
                    {{ item.node_name }}
                  </router-link>
                  <div class="tiny muted-2 mono">{{ item.node_uid }}</div>
                </td>
                <td><StatusTag :status="item.status" /></td>
                <td class="num text-right">{{ fmtNumber(item.value) }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      <div class="card">
        <div class="card-head">
          <div class="card-title"><i class="bar" />最近告警</div>
          <router-link class="btn btn-sm" to="/alerts">告警中心</router-link>
        </div>
        <div class="card-body tight">
          <EmptyState
            v-if="!recent.alerts.length"
            icon="shield"
            title="暂无告警"
            description="所有节点指标均在阈值范围内运行"
          />
          <div v-else class="alert-feed">
            <div v-for="item in recent.alerts" :key="item.id" class="alert-row">
              <span class="tag" :class="severityTone[item.severity]">{{ item.severity_label }}</span>
              <div class="grow">
                <div class="small ellipsis">{{ item.title }}</div>
                <div class="tiny muted-2">{{ item.content }}</div>
              </div>
              <div class="text-right nowrap">
                <div class="tiny muted-2">{{ relativeTime(item.started_at) }}</div>
                <span class="tag" :class="item.status === 'active' ? 'tag-critical' : item.status === 'acked' ? 'tag-minor' : 'tag-online'">
                  {{ item.status_label }}
                </span>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.dashboard { padding-bottom: 4px; }
.live-dot { width: 7px; height: 7px; border-radius: 50%; background: #93A9BE; display: inline-block; }
.live-dot.on { background: #2FB27C; box-shadow: 0 0 6px rgba(47, 178, 124, 0.7); }

.event-feed, .alert-feed { display: flex; flex-direction: column; }
.feed-row {
  display: flex; align-items: center; gap: 9px;
  padding: 8px 6px; border-bottom: 1px solid #F1F6FB;
}
.feed-row:last-child { border-bottom: none; }

.media-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 11px; padding: 4px; }
.media-thumb { display: block; border-radius: 9px; overflow: hidden; border: 1px solid var(--c-border); }
.media-thumb:hover { border-color: var(--c-primary-300); box-shadow: var(--shadow-sm); }
.thumb-box { position: relative; aspect-ratio: 4 / 3; background: var(--c-surface-3); overflow: hidden; }
.thumb-box img { width: 100%; height: 100%; object-fit: cover; display: block; }
.video-ph {
  width: 100%; height: 100%; display: flex; align-items: center; justify-content: center;
  background: linear-gradient(135deg, var(--c-primary-700), var(--c-deep)); color: var(--c-accent);
}
.type-chip {
  position: absolute; left: 6px; top: 6px;
  padding: 1px 6px; border-radius: 4px;
  background: rgba(10, 30, 50, 0.66); color: #fff; font-size: 10.5px;
}
.thumb-meta { padding: 6px 8px 7px; background: var(--c-surface); }

.rank {
  display: inline-flex; align-items: center; justify-content: center;
  width: 21px; height: 21px; border-radius: 6px;
  background: var(--c-surface-3); color: var(--c-text-2);
  font-size: 11.5px; font-weight: 600;
}
.rank.top { background: var(--c-primary-100); color: var(--c-primary-600); }
.node-link { font-weight: 500; }

.alert-row {
  display: flex; align-items: flex-start; gap: 10px;
  padding: 9px 6px; border-bottom: 1px solid #F1F6FB;
}
.alert-row:last-child { border-bottom: none; }
</style>
