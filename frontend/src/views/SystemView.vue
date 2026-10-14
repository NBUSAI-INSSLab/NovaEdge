<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api, fmtBytes, fmtNumber, fmtTime } from '@/api'
import { useUserStore } from '@/stores/user'
import { useToastStore } from '@/stores/toast'
import DataTable from '@/components/DataTable.vue'
import AppModal from '@/components/AppModal.vue'
import AppIcon from '@/components/AppIcon.vue'
import EChart from '@/components/EChart.vue'

const userStore = useUserStore()
const toast = useToastStore()
const route = useRoute()
const router = useRouter()

const TABS = [
  { key: 'info', label: '运行信息', icon: 'system' },
  { key: 'config', label: '参数配置', icon: 'sliders' },
  { key: 'metric', label: '物模型', icon: 'metric' },
  { key: 'upload', label: '上传通道', icon: 'upload' },
  { key: 'audit', label: '审计日志', icon: 'file-text' },
  { key: 'api', label: '接口清单', icon: 'git-branch' }
]

const initialTab = typeof route.query.tab === 'string' && TABS.some((t) => t.key === route.query.tab)
  ? route.query.tab
  : 'info'
const activeTab = ref(initialTab)

function switchTab(key) {
  activeTab.value = key
  const query = { ...route.query }
  if (key === 'info') delete query.tab
  else query.tab = key
  router.replace({ query })
}

watch(() => route.query.tab, (value) => {
  if (typeof value === 'string' && value && value !== activeTab.value && TABS.some((t) => t.key === value)) {
    activeTab.value = value
  }
})
const info = ref(null)
const configs = ref({ groups: {}, items: [] })
const storageUsage = ref([])
const endpoints = ref({})
const uploadSessions = ref([])
const uploadTotal = ref(0)
const uploadPage = ref(1)
const uploadLoading = ref(false)
const uploadFilter = ref('')
const auditLogs = ref([])
const auditTotal = ref(0)
const auditPage = ref(1)
const auditLoading = ref(false)
const maintenance = reactive({ days: 90, media_days: 0, busy: false })
const editingKey = ref('')
const editingValue = ref('')

const CATEGORY_LABELS = { app: '应用', node: '节点', storage: '存储', alert: '告警', common: '通用' }

/* ===== 物模型（指标字典） ===== */
const metricLoaded = ref(false)
const metricLoading = ref(false)
const metricRows = ref([])
const metricTotal = ref(0)
const metricPage = ref(1)
const metricPageSize = ref(20)
const metricDicts = ref({ data_types: [], categories: [] })
const metricFilters = reactive({ category: '', data_type: '', keyword: '' })

const showMetricForm = ref(false)
const editingMetric = ref(null)
const metricSubmitting = ref(false)
const metricForm = reactive({
  metric_key: '', name: '', data_type: 'float', unit: '', category: 'env',
  min_value: null, max_value: null, precision: 2, applicable_type: '',
  enumText: '', description: ''
})

const metricColumns = [
  { key: 'name', label: '指标' },
  { key: 'data_type', label: '数据类型', width: '104px' },
  { key: 'unit', label: '单位', width: '96px' },
  { key: 'category', label: '分类', width: '104px' },
  { key: 'range', label: '量程', width: '170px' },
  { key: 'sample_count', label: '采样量', width: '110px', align: 'right' },
  { key: 'source', label: '来源', width: '100px' },
  { key: 'actions', label: '操作', width: '150px' }
]

const METRIC_CATEGORY_TONE = {
  env: 'tag-teal', power: 'tag-major', motion: 'tag-purple',
  vision: 'tag-primary', system: 'tag-warning', custom: ''
}

async function loadMetrics() {
  metricLoading.value = true
  try {
    const res = await api.metrics.list({
      page: metricPage.value,
      page_size: metricPageSize.value,
      category: metricFilters.category || undefined,
      data_type: metricFilters.data_type || undefined,
      keyword: metricFilters.keyword || undefined
    })
    if (res.code === 0) {
      metricRows.value = res.data.items
      metricTotal.value = res.data.total
    }
  } finally {
    metricLoading.value = false
  }
}

async function ensureMetrics() {
  if (metricLoaded.value) return
  metricLoaded.value = true
  const res = await api.metrics.categories()
  if (res.code === 0) metricDicts.value = res.data
  loadMetrics()
}

function openMetricForm(metric = null) {
  editingMetric.value = metric
  if (metric) {
    Object.assign(metricForm, {
      metric_key: metric.metric_key, name: metric.name, data_type: metric.data_type,
      unit: metric.unit, category: metric.category, min_value: metric.min_value,
      max_value: metric.max_value, precision: metric.precision,
      applicable_type: metric.applicable_type,
      enumText: (metric.enum_options || []).join(','), description: metric.description
    })
  } else {
    Object.assign(metricForm, {
      metric_key: '', name: '', data_type: 'float', unit: '', category: 'env',
      min_value: null, max_value: null, precision: 2, applicable_type: '',
      enumText: '', description: ''
    })
  }
  showMetricForm.value = true
}

async function submitMetric() {
  if (!metricForm.metric_key.trim() || !metricForm.name.trim()) {
    toast.warning('请填写指标编码与名称')
    return
  }
  metricSubmitting.value = true
  const payload = {
    ...metricForm,
    metric_key: metricForm.metric_key.trim(),
    enum_options: metricForm.enumText.split(',').map((i) => i.trim()).filter(Boolean)
  }
  delete payload.enumText
  try {
    const res = editingMetric.value
      ? await api.metrics.update(editingMetric.value.id, payload)
      : await api.metrics.create(payload)
    if (res.code === 0) {
      toast.success(res.message)
      showMetricForm.value = false
      loadMetrics()
    } else toast.error(res.message)
  } finally {
    metricSubmitting.value = false
  }
}

async function removeMetric(metric) {
  if (!window.confirm(`确认删除指标「${metric.name}」？`)) return
  const res = await api.metrics.remove(metric.id)
  if (res.code === 0) { toast.success('指标已删除'); loadMetrics() } else toast.error(res.message)
}

const uploadColumns = [
  { key: 'file_name', label: '文件名' },
  { key: 'node_name', label: '来源节点', width: '180px' },
  { key: 'file_type', label: '类型', width: '90px' },
  { key: 'size', label: '大小', width: '110px', align: 'right' },
  { key: 'progress', label: '进度', width: '170px' },
  { key: 'status', label: '状态', width: '100px' },
  { key: 'created_at', label: '创建时间', width: '165px' }
]

const auditColumns = [
  { key: 'username', label: '操作人', width: '120px' },
  { key: 'action', label: '动作', width: '150px' },
  { key: 'target', label: '对象', width: '160px' },
  { key: 'detail', label: '详情' },
  { key: 'ip', label: '来源 IP', width: '136px' },
  { key: 'created_at', label: '时间', width: '165px' }
]

const ACTION_LABELS = {
  login: '登录平台', logout: '退出登录', change_password: '修改密码', delete_media: '删除媒体文件'
}

async function loadInfo() {
  const [infoRes, usageRes, epRes] = await Promise.all([
    api.system.info(), api.system.storageUsage(), api.system.endpoints()
  ])
  if (infoRes.code === 0) info.value = infoRes.data
  if (usageRes.code === 0) storageUsage.value = usageRes.data
  if (epRes.code === 0) endpoints.value = epRes.data
}

async function loadConfigs() {
  const res = await api.system.configs()
  if (res.code === 0) configs.value = res.data
}

async function loadUploads() {
  uploadLoading.value = true
  try {
    const res = await api.media.uploads({
      page: uploadPage.value, page_size: 15, status: uploadFilter.value || undefined
    })
    if (res.code === 0) {
      uploadSessions.value = res.data.items
      uploadTotal.value = res.data.total
    }
  } finally {
    uploadLoading.value = false
  }
}

async function loadAudit() {
  auditLoading.value = true
  try {
    const res = await api.users.auditLogs({ page: auditPage.value, page_size: 20 })
    if (res.code === 0) { auditLogs.value = res.data.items; auditTotal.value = res.data.total }
  } finally {
    auditLoading.value = false
  }
}

function startEdit(item) {
  editingKey.value = item.cfg_key
  const value = item.cfg_value
  editingValue.value = typeof value === 'object' ? JSON.stringify(value) : String(value)
}

async function saveConfig(item) {
  let value = editingValue.value
  try {
    value = JSON.parse(editingValue.value)
  } catch (e) { /* 保留原始字符串 */ }
  const res = await api.system.updateConfig(item.cfg_key, { value })
  if (res.code === 0) {
    toast.success('配置已保存')
    editingKey.value = ''
    loadConfigs()
  } else toast.error(res.message)
}

async function runRollup() {
  maintenance.busy = true
  try {
    const res = await api.system.rollup(24)
    if (res.code === 0) toast.success(res.message)
  } finally {
    maintenance.busy = false
  }
}

async function runCleanup() {
  const message = `确认执行数据清理？\n\n` +
    `· 删除 ${maintenance.days} 天前的遥测明细、心跳与节点日志\n` +
    (maintenance.media_days ? `· 删除 ${maintenance.media_days} 天前的媒体文件（含物理文件）\n` : '· 保留全部媒体文件\n') +
    `\n此操作不可恢复。`
  if (!window.confirm(message)) return
  maintenance.busy = true
  try {
    const res = await api.system.cleanup({
      retention_days: maintenance.days,
      media_retention_days: maintenance.media_days
    })
    if (res.code === 0) {
      const d = res.data
      toast.success(`清理完成：遥测 ${d.telemetry_deleted} 条 / 心跳 ${d.heartbeat_deleted} 条 / 资源 ${d.media_deleted} 个`)
      loadInfo()
    }
  } finally {
    maintenance.busy = false
  }
}

const metricCategoryOption = computed(() => {
  const counters = {}
  metricRows.value.forEach((item) => {
    counters[item.category_label] = (counters[item.category_label] || 0) + (item.sample_count || 0)
  })
  return {
    tooltip: { trigger: 'item', formatter: '{b}: {c} 条' },
    legend: { bottom: 0, icon: 'circle', itemWidth: 8, itemHeight: 8, textStyle: { color: '#567792', fontSize: 11.5 } },
    series: [{
      type: 'pie',
      radius: ['44%', '68%'],
      center: ['50%', '42%'],
      itemStyle: { borderColor: '#fff', borderWidth: 2 },
      label: { show: false },
      data: Object.entries(counters).map(([name, value]) => ({ name, value }))
    }]
  }
})

const storageOption = computed(() => {
  const labels = { image: '图片', video: '视频', other: '其他' }
  return {
    tooltip: { trigger: 'item', formatter: (p) => `${p.name}<br/>${p.value} 个 · ${fmtBytes(p.data.bytes)}` },
    legend: { bottom: 0, icon: 'circle', itemWidth: 8, itemHeight: 8, textStyle: { color: '#567792', fontSize: 11.5 } },
    series: [{
      type: 'pie',
      radius: ['46%', '70%'],
      center: ['50%', '42%'],
      itemStyle: { borderColor: '#fff', borderWidth: 2 },
      label: { show: false },
      data: storageUsage.value.map((item) => ({
        name: labels[item.file_type] || item.file_type,
        value: item.count,
        bytes: item.bytes
      }))
    }]
  }
})

const endpointCount = computed(() =>
  Object.values(endpoints.value).reduce((sum, list) => sum + list.length, 0)
)

onMounted(() => {
  loadInfo()
  loadConfigs()
  loadUploads()
  loadAudit()
  if (activeTab.value === 'metric') ensureMetrics()
})

watch(activeTab, (value) => {
  if (value === 'metric') ensureMetrics()
})
</script>

<template>
  <div>
    <!-- Tab -->
    <div class="card mb-16">
      <div class="card-body tight">
        <div class="tabs">
          <button
            v-for="tab in TABS"
            :key="tab.key"
            class="tab"
            :class="{ active: activeTab === tab.key }"
            @click="switchTab(tab.key)"
          >
            <AppIcon :name="tab.icon" :size="15" />{{ tab.label }}
          </button>
        </div>
      </div>
    </div>

    <!-- 运行信息 -->
    <template v-if="activeTab === 'info'">
      <div class="grid-3 mb-16">
        <div class="card">
          <div class="card-head"><div class="card-title"><i class="bar" />应用信息</div></div>
          <div class="card-body">
            <div class="info-row"><span>平台名称</span><strong>{{ info?.app.name || '—' }}</strong></div>
            <div class="info-row"><span>版本</span><strong>{{ info?.app.version }}</strong></div>
            <div class="info-row"><span>接口前缀</span><strong class="mono">{{ info?.app.api_prefix }}</strong></div>
            <div class="info-row"><span>持续运行</span><strong>{{ Math.floor((info?.app.uptime_seconds || 0) / 60) }} 分钟</strong></div>
            <div class="info-row"><span>服务端时间</span><strong class="mono">{{ fmtTime(info?.app.server_time) }}</strong></div>
          </div>
        </div>

        <div class="card">
          <div class="card-head"><div class="card-title"><i class="bar" />数据库</div></div>
          <div class="card-body">
            <div class="info-row"><span>引擎</span>
              <strong>
                <span class="tag" :class="info?.database.type === 'mysql' ? 'tag-teal' : 'tag-primary'">
                  {{ info?.database.dialect === 'mysql' ? 'MySQL（生产）' : 'SQLite（开发测试）' }}
                </span>
              </strong>
            </div>
            <div class="info-row"><span>连接串</span><strong class="mono tiny ellipsis">{{ info?.database.uri_masked }}</strong></div>
            <div class="info-row"><span>数据表数量</span><strong>{{ info?.database.tables }} 张</strong></div>
            <div class="info-row"><span>遥测数据点</span><strong>{{ fmtNumber(info?.counts.telemetry) }}</strong></div>
            <div class="info-row"><span>已登记指标</span><strong>{{ fmtNumber(info?.counts.metrics) }}</strong></div>
          </div>
        </div>

        <div class="card">
          <div class="card-head"><div class="card-title"><i class="bar" />存储与消息通道</div></div>
          <div class="card-body">
            <div class="info-row"><span>存储模式</span><strong>{{ info?.storage.mode === 'local' ? '本地磁盘' : info?.storage.mode }}</strong></div>
            <div class="info-row"><span>存储路径</span><strong class="mono tiny ellipsis" :title="info?.storage.root">{{ info?.storage.root }}</strong></div>
            <div class="info-row"><span>占用空间</span><strong>{{ fmtBytes(info?.storage.usage_bytes) }}</strong></div>
            <div class="info-row"><span>图片分片</span><strong>{{ fmtBytes(info?.storage.chunk_size) }}</strong></div>
            <div class="info-row"><span>视频分片</span><strong>{{ fmtBytes(info?.storage.large_chunk_size) }}</strong></div>
            <div class="info-row"><span>MQTT 通道</span>
              <strong>
                <span class="tag" :class="info?.mqtt.enabled ? 'tag-online' : 'tag-offline'">
                  {{ info?.mqtt.enabled ? `已启用 ${info.mqtt.host}:${info.mqtt.port}` : '未启用（HTTP 接入）' }}
                </span>
              </strong>
            </div>
          </div>
        </div>
      </div>

      <div class="grid-2 mb-16">
        <div class="card">
          <div class="card-head"><div class="card-title"><i class="bar" />存储占用分布</div></div>
          <div class="card-body"><EChart :option="storageOption" :height="220" /></div>
        </div>

        <div class="card">
          <div class="card-head">
            <div class="card-title"><i class="bar" />数据生命周期维护</div>
            <AppIcon name="info" :size="15" />
          </div>
          <div class="card-body">
            <p class="small muted" style="margin: 0 0 14px; line-height: 1.8">
              生产环境建议通过系统定时任务在低峰期执行：每小时做一次<b>小时级聚合</b>（长周期曲线走聚合表，
              查询更快），每日做一次<b>超期数据清理</b>。清理只删除时序明细，不会删除节点、物模型与告警历史。
            </p>
            <div class="form-grid">
              <div class="field">
                <label class="field-label">遥测明细保留天数</label>
                <input v-model.number="maintenance.days" class="input" type="number" min="1" />
              </div>
              <div class="field">
                <label class="field-label">媒体文件保留天数（0 = 永久保留）</label>
                <input v-model.number="maintenance.media_days" class="input" type="number" min="0" />
              </div>
            </div>
            <div class="row gap-8 mt-16">
              <button class="btn" :disabled="maintenance.busy || !userStore.canOperate" @click="runRollup">
                <AppIcon name="layers" :size="14" />执行小时聚合
              </button>
              <button class="btn btn-danger" :disabled="maintenance.busy || !userStore.canOperate" @click="runCleanup">
                <AppIcon name="trash" :size="14" />执行数据清理
              </button>
            </div>
          </div>
        </div>
      </div>
    </template>

    <!-- 参数配置 -->
    <template v-else-if="activeTab === 'config'">
      <div class="card">
        <div class="card-head">
          <div class="card-title"><i class="bar" />平台运行参数</div>
          <span class="muted small">共 {{ configs.items?.length || 0 }} 项</span>
        </div>
        <div class="card-body flush">
          <div v-for="(list, category) in configs.groups" :key="category" class="cfg-group">
            <div class="cfg-group-title">{{ CATEGORY_LABELS[category] || category }}</div>
            <div v-for="item in list" :key="item.cfg_key" class="cfg-row">
              <div class="cfg-main">
                <div class="small mono">{{ item.cfg_key }}</div>
                <div class="tiny muted-2">{{ item.description }}</div>
              </div>
              <div class="cfg-value">
                <template v-if="editingKey === item.cfg_key">
                  <input v-model="editingValue" class="input" style="max-width: 220px" @keyup.enter="saveConfig(item)" />
                  <button class="btn btn-sm btn-primary" @click="saveConfig(item)">保存</button>
                  <button class="btn btn-sm btn-ghost" @click="editingKey = ''">取消</button>
                </template>
                <template v-else>
                  <span class="mono small">{{ typeof item.cfg_value === 'object' ? JSON.stringify(item.cfg_value) : item.cfg_value }}</span>
                  <button v-if="userStore.canOperate" class="btn btn-sm" @click="startEdit(item)">
                    <AppIcon name="edit" :size="13" />修改
                  </button>
                </template>
              </div>
            </div>
          </div>
        </div>
      </div>
    </template>

    <!-- 物模型 -->
    <template v-else-if="activeTab === 'metric'">
      <div class="grid-3 mb-16">
        <div class="card">
          <div class="card-head"><div class="card-title"><i class="bar" />指标分类构成</div></div>
          <div class="card-body"><EChart :option="metricCategoryOption" :height="200" /></div>
        </div>
        <div class="card">
          <div class="card-head"><div class="card-title"><i class="bar" />物模型说明</div></div>
          <div class="card-body">
            <p class="small muted" style="line-height: 1.9; margin: 0">
              物模型用于屏蔽不同传感器厂商的数据口径差异：节点上报任意 <span class="mono">metric</span> 编码后，
              平台会自动登记为指标，并在此统一维护中文名称、单位、量程与精度。
              配置后，看板、曲线与告警规则都会按统一口径呈现。
            </p>
            <div class="tips">
              <div class="tip-item"><AppIcon name="check-circle" :size="15" />自动登记：节点首报即入库</div>
              <div class="tip-item"><AppIcon name="check-circle" :size="15" />量程校验：超出范围标记为可疑数据</div>
              <div class="tip-item"><AppIcon name="check-circle" :size="15" />告警引用：规则直接绑定指标编码</div>
            </div>
          </div>
        </div>
        <div class="card">
          <div class="card-head"><div class="card-title"><i class="bar" />快捷筛选</div></div>
          <div class="card-body">
            <div class="field mb-10">
              <label class="field-label">指标分类</label>
              <select v-model="metricFilters.category" class="select" @change="metricPage = 1; loadMetrics()">
                <option value="">全部分类</option>
                <option v-for="item in metricDicts.categories" :key="item.value" :value="item.value">{{ item.label }}</option>
              </select>
            </div>
            <div class="field mb-10">
              <label class="field-label">数据类型</label>
              <select v-model="metricFilters.data_type" class="select" @change="metricPage = 1; loadMetrics()">
                <option value="">全部类型</option>
                <option v-for="item in metricDicts.data_types" :key="item.value" :value="item.value">{{ item.label }}</option>
              </select>
            </div>
            <div class="row gap-8">
              <button class="btn grow" @click="metricFilters.category = ''; metricFilters.data_type = ''; metricFilters.keyword = ''; metricPage = 1; loadMetrics()">
                重置筛选
              </button>
              <button v-if="userStore.canOperate" class="btn btn-primary grow" @click="openMetricForm()">
                <AppIcon name="plus" :size="14" />新建指标
              </button>
            </div>
          </div>
        </div>
      </div>

      <div class="card">
        <div class="card-head">
          <div class="card-title"><i class="bar" />指标字典（物模型）</div>
          <div class="row gap-8">
            <div class="search-box">
              <AppIcon name="search" :size="15" />
              <input v-model="metricFilters.keyword" class="search-input" placeholder="搜索指标编码或名称" @keyup.enter="metricPage = 1; loadMetrics()" />
            </div>
            <button class="btn btn-sm" @click="loadMetrics"><AppIcon name="refresh" :size="14" />刷新</button>
          </div>
        </div>
        <div class="card-body flush">
          <DataTable
            v-model:page="metricPage"
            :columns="metricColumns"
            :rows="metricRows"
            :loading="metricLoading"
            :total="metricTotal"
            :page-size="metricPageSize"
            min-width="1000px"
            empty-text="暂无指标定义"
            @update:page="loadMetrics"
          >
            <template #cell-name="{ row }">
              <div class="small"><strong>{{ row.name }}</strong></div>
              <div class="tiny muted-2 mono">{{ row.metric_key }}</div>
            </template>
            <template #cell-data_type="{ row }">
              <span class="tag tag-primary">{{ row.data_type_label }}</span>
            </template>
            <template #cell-unit="{ row }"><span class="mono small">{{ row.unit || '—' }}</span></template>
            <template #cell-category="{ row }">
              <span class="tag" :class="METRIC_CATEGORY_TONE[row.category]">{{ row.category_label }}</span>
            </template>
            <template #cell-range="{ row }">
              <span class="mono small">
                {{ row.min_value !== null || row.max_value !== null
                  ? `${row.min_value ?? '—'} ~ ${row.max_value ?? '—'}`
                  : '—' }}
              </span>
              <div class="tiny muted-2">精度 {{ row.precision }} 位</div>
            </template>
            <template #cell-sample_count="{ row }"><span class="num">{{ fmtNumber(row.sample_count) }}</span></template>
            <template #cell-source="{ row }">
              <span class="tag" :class="row.is_system ? 'tag-warning' : 'tag-teal'">{{ row.is_system ? '系统内置' : '自动登记' }}</span>
            </template>
            <template #cell-actions="{ row }">
              <div class="actions">
                <button v-if="userStore.canOperate" class="btn btn-sm" @click="openMetricForm(row)">
                  <AppIcon name="edit" :size="13" />编辑
                </button>
                <button v-if="userStore.canOperate && !row.is_system" class="btn btn-sm btn-danger" @click="removeMetric(row)">
                  <AppIcon name="trash" :size="13" />
                </button>
                <span v-else-if="row.is_system" class="tiny muted-2">内置指标不可删除</span>
              </div>
            </template>
          </DataTable>
        </div>
      </div>
    </template>

    <!-- 上传通道 -->
    <template v-else-if="activeTab === 'upload'">
      <div class="card">
        <div class="card-head">
          <div class="card-title"><i class="bar" />文件上传会话</div>
          <div class="row gap-8">
            <select v-model="uploadFilter" class="select" style="width: 140px" @change="uploadPage = 1; loadUploads()">
              <option value="">全部状态</option>
              <option value="uploading">上传中</option>
              <option value="init">已初始化</option>
              <option value="failed">失败</option>
              <option value="done">已完成</option>
            </select>
            <button class="btn btn-sm" @click="loadUploads"><AppIcon name="refresh" :size="14" />刷新</button>
          </div>
        </div>
        <div class="card-body flush">
          <DataTable
            v-model:page="uploadPage"
            :columns="uploadColumns"
            :rows="uploadSessions"
            :loading="uploadLoading"
            :total="uploadTotal"
            :page-size="15"
            min-width="1080px"
            empty-text="暂无上传会话记录"
            @update:page="loadUploads"
          >
            <template #cell-size="{ row }"><span class="num">{{ fmtBytes(row.file_size) }}</span></template>
            <template #cell-progress="{ row }">
              <div class="row gap-8">
                <div class="progress-track">
                  <div class="progress-fill" :class="{ done: row.status === 'done' }" :style="{ width: `${row.progress}%` }" />
                </div>
                <span class="tiny mono nowrap">{{ row.received_chunks }}/{{ row.total_chunks }}</span>
              </div>
            </template>
            <template #cell-status="{ row }">
              <span class="tag" :class="{
                'tag-primary': ['uploading', 'init'].includes(row.status),
                'tag-online': row.status === 'done',
                'tag-critical': row.status === 'failed',
                'tag-offline': row.status === 'aborted'
              }">{{ { uploading: '上传中', init: '已初始化', done: '已完成', failed: '失败', aborted: '已取消', merging: '合并中' }[row.status] || row.status }}</span>
            </template>
            <template #cell-created_at="{ row }"><span class="small mono">{{ fmtTime(row.created_at) }}</span></template>
          </DataTable>
        </div>
      </div>
    </template>

    <!-- 审计日志 -->
    <template v-else-if="activeTab === 'audit'">
      <div class="card">
        <div class="card-head">
          <div class="card-title"><i class="bar" />操作审计日志</div>
          <button class="btn btn-sm" @click="loadAudit"><AppIcon name="refresh" :size="14" />刷新</button>
        </div>
        <div class="card-body flush">
          <DataTable
            v-model:page="auditPage"
            :columns="auditColumns"
            :rows="auditLogs"
            :loading="auditLoading"
            :total="auditTotal"
            :page-size="20"
            min-width="960px"
            empty-text="暂无审计记录"
            @update:page="loadAudit"
          >
            <template #cell-action="{ row }">
              <span class="tag tag-primary">{{ ACTION_LABELS[row.action] || row.action }}</span>
            </template>
            <template #cell-target="{ row }">
              <span class="small mono">{{ row.target_type }}{{ row.target_id ? `#${row.target_id}` : '' }}</span>
            </template>
            <template #cell-detail="{ row }">
              <span class="tiny muted mono ellipsis" :title="JSON.stringify(row.detail)">{{ JSON.stringify(row.detail || {}) }}</span>
            </template>
            <template #cell-ip="{ row }"><span class="small mono">{{ row.ip || '—' }}</span></template>
            <template #cell-created_at="{ row }"><span class="small mono">{{ fmtTime(row.created_at) }}</span></template>
          </DataTable>
        </div>
      </div>
    </template>

    <!-- 接口清单 -->
    <template v-else>
      <div class="card">
        <div class="card-head">
          <div class="card-title"><i class="bar" />已注册接口清单</div>
          <span class="tag tag-primary">共 {{ endpointCount }} 个接口</span>
        </div>
        <div class="card-body">
          <div v-for="(list, group) in endpoints" :key="group" class="api-group">
            <div class="api-group-title">
              <AppIcon name="folder" :size="15" />
              <span class="mono">/api/v1/{{ group }}</span>
              <span class="tag">{{ list.length }} 个</span>
            </div>
            <div class="api-list">
              <div v-for="item in list" :key="item.endpoint" class="api-item">
                <span class="method" :class="item.methods.includes('GET') ? 'get' : item.methods.includes('DELETE') ? 'del' : 'post'">
                  {{ item.methods[0] }}
                </span>
                <span class="mono small grow ellipsis">{{ item.path }}</span>
                <span class="tiny muted-2 mono">{{ item.endpoint }}</span>
              </div>
            </div>
          </div>
        </div>
      </div>
    </template>

    <AppModal
      v-model="showMetricForm"
      :title="editingMetric ? `编辑指标 · ${editingMetric.name}` : '新建指标'"
      size="lg"
      :loading="metricSubmitting"
      @confirm="submitMetric"
    >
      <div class="form-grid">
        <div class="field">
          <label class="field-label">指标编码<span class="req">*</span></label>
          <input v-model="metricForm.metric_key" class="input" placeholder="如 temperature" :disabled="!!editingMetric" />
          <span class="field-hint">节点上报时使用的 key，建议使用英文小写与下划线</span>
        </div>
        <div class="field">
          <label class="field-label">中文名称<span class="req">*</span></label>
          <input v-model="metricForm.name" class="input" placeholder="如 空气温度" />
        </div>
        <div class="field">
          <label class="field-label">数据类型</label>
          <select v-model="metricForm.data_type" class="select">
            <option v-for="item in metricDicts.data_types" :key="item.value" :value="item.value">{{ item.label }}</option>
          </select>
        </div>
        <div class="field">
          <label class="field-label">单位</label>
          <input v-model="metricForm.unit" class="input" placeholder="如 ℃ / %RH / lux" />
        </div>
        <div class="field">
          <label class="field-label">分类</label>
          <select v-model="metricForm.category" class="select">
            <option v-for="item in metricDicts.categories" :key="item.value" :value="item.value">{{ item.label }}</option>
          </select>
        </div>
        <div class="field">
          <label class="field-label">小数位数</label>
          <input v-model.number="metricForm.precision" class="input" type="number" min="0" max="6" />
        </div>
        <div class="field">
          <label class="field-label">量程下限</label>
          <input v-model.number="metricForm.min_value" class="input" type="number" />
        </div>
        <div class="field">
          <label class="field-label">量程上限</label>
          <input v-model.number="metricForm.max_value" class="input" type="number" />
        </div>
        <div class="field span-2">
          <label class="field-label">枚举可选值（英文逗号分隔，仅枚举类型需要）</label>
          <input v-model="metricForm.enumText" class="input" placeholder="如 normal,warning,fault" />
        </div>
        <div class="field span-2">
          <label class="field-label">指标说明</label>
          <input v-model="metricForm.description" class="input" placeholder="选填" />
        </div>
      </div>
    </AppModal>
  </div>
</template>

<style scoped>
.tabs { display: flex; gap: 4px; flex-wrap: wrap; }
.tab {
  display: flex; align-items: center; gap: 6px;
  height: 32px; padding: 0 14px; border: none; border-radius: 8px;
  background: transparent; color: var(--c-text-2);
  font-family: inherit; font-size: 13px; cursor: pointer;
}
.tab:hover { background: var(--c-surface-3); color: var(--c-primary); }
.tab.active { background: var(--c-primary-100); color: var(--c-primary-600); font-weight: 600; }

.info-row {
  display: flex; align-items: center; justify-content: space-between; gap: 12px;
  padding: 7px 0; border-bottom: 1px dashed #EDF2F8; font-size: 12.5px;
}
.info-row:last-child { border-bottom: none; }
.info-row span { color: var(--c-text-3); flex-shrink: 0; }
.info-row strong { font-weight: 500; text-align: right; min-width: 0; overflow: hidden; text-overflow: ellipsis; }

.cfg-group { border-bottom: 8px solid var(--c-bg); }
.cfg-group:last-child { border-bottom: none; }
.cfg-group-title {
  padding: 11px 20px; font-size: 12.5px; font-weight: 600;
  color: var(--c-text-2); background: var(--c-surface-2);
}
.cfg-row {
  display: flex; align-items: center; justify-content: space-between; gap: 16px;
  padding: 12px 20px; border-bottom: 1px solid #F1F6FB;
}
.cfg-row:last-child { border-bottom: none; }
.cfg-main { min-width: 0; }
.cfg-value { display: flex; align-items: center; gap: 8px; flex-shrink: 0; }

.progress-track {
  width: 96px; height: 6px; border-radius: 3px;
  background: var(--c-surface-3); overflow: hidden;
}
.progress-fill {
  height: 100%; border-radius: 3px;
  background: linear-gradient(90deg, var(--c-primary-300), var(--c-primary));
  transition: width 0.3s;
}
.progress-fill.done { background: linear-gradient(90deg, #5CC79A, #23A06B); }

.api-group { margin-bottom: 18px; }
.api-group-title {
  display: flex; align-items: center; gap: 8px;
  padding: 8px 12px; border-radius: 8px;
  background: var(--c-surface-2); font-size: 13px; font-weight: 600;
}
.api-list { margin-top: 7px; display: flex; flex-direction: column; gap: 3px; }
.api-item {
  display: flex; align-items: center; gap: 10px;
  padding: 6px 12px; border-radius: 6px; font-size: 12.5px;
}
.api-item:hover { background: var(--c-primary-50); }
.method {
  width: 52px; text-align: center; flex-shrink: 0;
  padding: 1px 0; border-radius: 4px; font-size: 10.5px; font-weight: 700;
}
.method.get { background: var(--c-green-100); color: #17804F; }
.method.post { background: var(--c-primary-100); color: var(--c-primary-600); }
.method.del { background: var(--c-red-100); color: #B33131; }

.tips { margin-top: 14px; display: flex; flex-direction: column; gap: 8px; }
.tip-item {
  display: flex; align-items: center; gap: 7px;
  font-size: 12.5px; color: var(--c-text-2);
}
.tip-item :deep(.icon) { color: var(--c-green); }
.search-box {
  display: flex; align-items: center; gap: 7px;
  height: 30px; padding: 0 10px; min-width: 220px;
  border: 1px solid var(--c-border-strong); border-radius: var(--radius-sm);
  background: var(--c-surface); color: var(--c-text-3);
}
.search-box:focus-within { border-color: var(--c-primary); box-shadow: 0 0 0 3px var(--c-primary-100); }
.search-input { flex: 1; border: none; outline: none; background: transparent; font-family: inherit; font-size: 13px; min-width: 0; }
.field-hint { font-size: 11.5px; color: var(--c-text-3); }
</style>
