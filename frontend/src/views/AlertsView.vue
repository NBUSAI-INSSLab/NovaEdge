<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { api, fmtNumber, fmtTime, relativeTime } from '@/api'
import { useUserStore } from '@/stores/user'
import { useRealtimeStore } from '@/stores/realtime'
import { useChartColors } from '@/utils/chartPalette'
import { useToastStore } from '@/stores/toast'
import DataTable from '@/components/DataTable.vue'
import AppModal from '@/components/AppModal.vue'
import AppIcon from '@/components/AppIcon.vue'
import EChart from '@/components/EChart.vue'

const userStore = useUserStore()
const realtime = useRealtimeStore()
const chartC = useChartColors()
const toast = useToastStore()

const activeTab = ref('records')
const summary = ref({ active_total: 0, by_severity: {}, today_total: 0, recent: [] })
const dicts = ref({ severities: [], operators: [] })
const nodes = ref([])
const metrics = ref([])

/* ------------------------------- 告警记录 ------------------------------- */
const recordLoading = ref(false)
const records = ref([])
const recordTotal = ref(0)
const recordPage = ref(1)
const recordPageSize = ref(15)
const selectedRecords = ref([])
const recordFilters = reactive({ status: '', severity: '', node_id: '', hours: 24 })

const recordColumns = [
  { key: 'severity', label: '级别', width: '88px' },
  { key: 'title', label: '告警标题' },
  { key: 'content', label: '触发详情', width: '330px' },
  { key: 'status', label: '状态', width: '92px' },
  { key: 'count', label: '次数', width: '70px', align: 'right' },
  { key: 'started_at', label: '发生时间', width: '165px' },
  { key: 'actions', label: '操作', width: '172px' }
]

async function loadRecords() {
  recordLoading.value = true
  try {
    const res = await api.alerts.records({
      page: recordPage.value,
      page_size: recordPageSize.value,
      status: recordFilters.status || undefined,
      severity: recordFilters.severity || undefined,
      node_id: recordFilters.node_id || undefined,
      hours: recordFilters.hours || undefined
    })
    if (res.code === 0) {
      records.value = res.data.items
      recordTotal.value = res.data.total
    }
  } finally {
    recordLoading.value = false
  }
}

async function loadSummary() {
  const res = await api.alerts.summary()
  if (res.code === 0) summary.value = res.data
}

async function ack(record) {
  const res = await api.alerts.ack(record.id)
  if (res.code === 0) { toast.success('告警已确认'); loadRecords(); loadSummary() } else toast.error(res.message)
}

async function clearRecord(record) {
  const res = await api.alerts.clear(record.id)
  if (res.code === 0) { toast.success('告警已恢复'); loadRecords(); loadSummary() } else toast.error(res.message)
}

async function batchAck() {
  if (!selectedRecords.value.length) { toast.warning('请先勾选告警'); return }
  const res = await api.alerts.batchAck(selectedRecords.value)
  if (res.code === 0) {
    toast.success(res.message)
    selectedRecords.value = []
    loadRecords(); loadSummary()
  }
}

function resetRecordFilters() {
  recordFilters.status = ''
  recordFilters.severity = ''
  recordFilters.node_id = ''
  recordFilters.hours = 24
  recordPage.value = 1
  loadRecords()
}

/* ------------------------------- 告警规则 ------------------------------- */
const ruleLoading = ref(false)
const rules = ref([])
const ruleTotal = ref(0)
const rulePage = ref(1)
const showRuleForm = ref(false)
const editingRule = ref(null)
const submitting = ref(false)
const ruleForm = reactive({
  name: '', node_id: 0, metric_key: '', operator: 'gt', threshold: 0,
  threshold2: null, duration_sec: 60, severity: 'major', silence_sec: 300,
  enabled: true, description: ''
}, 'alerts')

const ruleColumns = [
  { key: 'name', label: '规则名称' },
  { key: 'scope', label: '生效范围', width: '150px' },
  { key: 'condition', label: '触发条件', width: '230px' },
  { key: 'duration_sec', label: '持续', width: '86px', align: 'right' },
  { key: 'severity', label: '级别', width: '88px' },
  { key: 'enabled', label: '状态', width: '88px' },
  { key: 'trigger_count', label: '触发次数', width: '96px', align: 'right' },
  { key: 'actions', label: '操作', width: '150px' }
]

async function loadRules() {
  ruleLoading.value = true
  try {
    const res = await api.alerts.rules({ page: rulePage.value, page_size: 15 })
    if (res.code === 0) {
      rules.value = res.data.items
      ruleTotal.value = res.data.total
    }
  } finally {
    ruleLoading.value = false
  }
}

function openRuleForm(rule = null) {
  editingRule.value = rule
  if (rule) {
    Object.assign(ruleForm, {
      name: rule.name, node_id: rule.node_id || 0, metric_key: rule.metric_key,
      operator: rule.operator, threshold: rule.threshold, threshold2: rule.threshold2,
      duration_sec: rule.duration_sec, severity: rule.severity,
      silence_sec: rule.silence_sec, enabled: rule.enabled, description: rule.description
    })
  } else {
    Object.assign(ruleForm, {
      name: '', node_id: 0, metric_key: metrics.value[0]?.metric_key || '',
      operator: 'gt', threshold: 0, threshold2: null, duration_sec: 60,
      severity: 'major', silence_sec: 300, enabled: true, description: ''
    })
  }
  showRuleForm.value = true
}

async function submitRule() {
  if (!ruleForm.name.trim() || !ruleForm.metric_key) {
    toast.warning('请填写规则名称并选择监测指标')
    return
  }
  submitting.value = true
  try {
    const res = editingRule.value
      ? await api.alerts.updateRule(editingRule.value.id, { ...ruleForm })
      : await api.alerts.createRule({ ...ruleForm })
    if (res.code === 0) {
      toast.success(res.message)
      showRuleForm.value = false
      loadRules()
    } else toast.error(res.message)
  } finally {
    submitting.value = false
  }
}

async function toggleRule(rule) {
  const res = await api.alerts.updateRule(rule.id, { enabled: !rule.enabled })
  if (res.code === 0) { toast.success(rule.enabled ? '规则已停用' : '规则已启用'); loadRules() }
}

async function removeRule(rule) {
  if (!window.confirm(`确认删除告警规则「${rule.name}」？`)) return
  const res = await api.alerts.removeRule(rule.id)
  if (res.code === 0) { toast.success('规则已删除'); loadRules() }
}

/* ------------------------------- 图表 ------------------------------- */
const severityOption = computed(() => {
  const map = summary.value.by_severity || {}
  const labels = { critical: '紧急', major: '严重', minor: '一般', warning: '提示' }
  const colors = { critical: '#D34848', major: '#DE8A1B', minor: '#E8B84B', warning: chartC.value.primary }
  return {
    tooltip: { trigger: 'item', formatter: '{b}: {c} 条 ({d}%)' },
    legend: { bottom: 0, icon: 'circle', itemWidth: 8, itemHeight: 8, textStyle: { color: '#567792', fontSize: 11.5 } },
    series: [{
      type: 'pie',
      radius: ['46%', '70%'],
      center: ['50%', '42%'],
      itemStyle: { borderColor: '#fff', borderWidth: 2 },
      label: { show: false },
      data: Object.entries(map).map(([key, value]) => ({
        name: labels[key] || key, value, itemStyle: { color: colors[key] }
      }))
    }]
  }
})

const severityTone = { critical: 'tag-critical', major: 'tag-major', minor: 'tag-minor', warning: 'tag-warning' }
const operatorText = (rule) => {
  const label = rule.operator_label
  if (rule.operator === 'out_of_range') return `超出 ${rule.threshold} ~ ${rule.threshold2}`
  return `${label} ${rule.threshold}`
}

realtime.connect({
  // 页面级订阅
  onAlert: () => { loadSummary(); if (activeTab.value === 'records') loadRecords() }
}, 'alerts')

onMounted(async () => {
  const [dictRes, nodeRes, metricRes] = await Promise.all([
    api.alerts.dicts(), api.nodes.list({ page: 1, page_size: 100 }), api.metrics.list({ page: 1, page_size: 200 })
  ])
  if (dictRes.code === 0) dicts.value = dictRes.data
  if (nodeRes.code === 0) nodes.value = nodeRes.data.items
  if (metricRes.code === 0) metrics.value = metricRes.data.items
  loadSummary()
  loadRecords()
  loadRules()
})
</script>

<template>
  <div>
    <!-- 概览 -->
    <div class="grid-4 mb-16">
      <div class="stat tone-red">
        <div class="stat-icon"><AppIcon name="alert" :size="19" /></div>
        <div>
          <div class="stat-label">待处理告警</div>
          <div class="stat-value">{{ summary.active_total }}</div>
        </div>
      </div>
      <div class="stat tone-amber">
        <div class="stat-icon"><AppIcon name="clock" :size="19" /></div>
        <div>
          <div class="stat-label">今日新增告警</div>
          <div class="stat-value">{{ summary.today_total }}</div>
        </div>
      </div>
      <div class="stat tone-primary">
        <div class="stat-icon"><AppIcon name="sliders" :size="19" /></div>
        <div>
          <div class="stat-label">启用中的规则</div>
          <div class="stat-value">{{ rules.filter((r) => r.enabled).length }}<em>/ {{ ruleTotal }}</em></div>
        </div>
      </div>
      <div class="card" style="padding: 6px 10px">
        <EChart :option="severityOption" :height="112" />
      </div>
    </div>

    <!-- Tab 切换 -->
    <div class="card">
      <div class="card-head">
        <div class="tabs">
          <button class="tab" :class="{ active: activeTab === 'records' }" @click="activeTab = 'records'">
            <AppIcon name="alert" :size="15" />告警记录
          </button>
          <button class="tab" :class="{ active: activeTab === 'rules' }" @click="activeTab = 'rules'">
            <AppIcon name="sliders" :size="15" />告警规则
          </button>
        </div>
        <div class="row gap-8">
          <template v-if="activeTab === 'records'">
            <button v-if="selectedRecords.length" class="btn btn-sm" @click="batchAck">
              <AppIcon name="check" :size="14" />批量确认（{{ selectedRecords.length }}）
            </button>
            <button class="btn btn-sm" @click="loadRecords"><AppIcon name="refresh" :size="14" />刷新</button>
          </template>
          <template v-else>
            <button class="btn btn-sm" @click="loadRules"><AppIcon name="refresh" :size="14" />刷新</button>
            <button v-if="userStore.canOperate" class="btn btn-sm btn-primary" @click="openRuleForm()">
              <AppIcon name="plus" :size="14" />新建规则
            </button>
          </template>
        </div>
      </div>

      <div class="card-body">
        <!-- 记录 -->
        <template v-if="activeTab === 'records'">
          <div class="filter-row mb-10">
            <select v-model="recordFilters.status" class="select" style="width: 128px" @change="recordPage = 1; loadRecords()">
              <option value="">全部状态</option>
              <option value="active">待处理</option>
              <option value="acked">已确认</option>
              <option value="cleared">已恢复</option>
            </select>
            <select v-model="recordFilters.severity" class="select" style="width: 118px" @change="recordPage = 1; loadRecords()">
              <option value="">全部级别</option>
              <option v-for="item in dicts.severities" :key="item.value" :value="item.value">{{ item.label }}</option>
            </select>
            <select v-model="recordFilters.node_id" class="select" style="width: 190px" @change="recordPage = 1; loadRecords()">
              <option value="">全部节点</option>
              <option v-for="node in nodes" :key="node.id" :value="node.id">{{ node.name }}</option>
            </select>
            <select v-model="recordFilters.hours" class="select" style="width: 128px" @change="recordPage = 1; loadRecords()">
              <option :value="6">近 6 小时</option>
              <option :value="24">近 24 小时</option>
              <option :value="168">近 7 天</option>
              <option :value="720">近 30 天</option>
            </select>
            <button class="btn btn-ghost" @click="resetRecordFilters">重置</button>
          </div>

          <DataTable
            v-model:page="recordPage"
            v-model:selected="selectedRecords"
            :columns="recordColumns"
            :rows="records"
            :loading="recordLoading"
            :total="recordTotal"
            :page-size="recordPageSize"
            selectable
            min-width="1160px"
            empty-text="暂无告警记录，节点指标均在阈值范围内"
            @update:page="loadRecords"
          >
            <template #cell-severity="{ row }">
              <span class="tag" :class="severityTone[row.severity]">{{ row.severity_label }}</span>
            </template>
            <template #cell-title="{ row }">
              <div class="small"><strong>{{ row.title }}</strong></div>
              <div class="tiny muted-2">{{ row.node_name }} · {{ row.metric_key }}</div>
            </template>
            <template #cell-content="{ row }">
              <div class="small muted ellipsis" :title="row.content">{{ row.content }}</div>
              <div class="tiny muted-2" v-if="row.clear_value !== null && row.clear_value !== undefined">
                恢复值 {{ row.clear_value }}
              </div>
            </template>
            <template #cell-status="{ row }">
              <span class="tag" :class="row.status === 'active' ? 'tag-critical' : row.status === 'acked' ? 'tag-warning' : 'tag-online'">
                {{ row.status_label }}
              </span>
            </template>
            <template #cell-count="{ row }"><span class="num">{{ row.count }}</span></template>
            <template #cell-started_at="{ row }">
              <div class="small mono">{{ fmtTime(row.started_at) }}</div>
              <div class="tiny muted-2">{{ relativeTime(row.started_at) }}</div>
            </template>
            <template #cell-actions="{ row }">
              <div class="actions">
                <button v-if="userStore.canOperate && row.status === 'active'" class="btn btn-sm" @click="ack(row)">
                  <AppIcon name="check" :size="13" />确认
                </button>
                <button v-if="userStore.canOperate && row.status !== 'cleared'" class="btn btn-sm" @click="clearRecord(row)">
                  <AppIcon name="check-circle" :size="13" />恢复
                </button>
                <router-link class="btn btn-sm" :to="`/nodes/${row.node_id}`">
                  <AppIcon name="node" :size="13" />节点
                </router-link>
              </div>
            </template>
          </DataTable>
        </template>

        <!-- 规则 -->
        <DataTable
          v-else
          v-model:page="rulePage"
          :columns="ruleColumns"
          :rows="rules"
          :loading="ruleLoading"
          :total="ruleTotal"
          :page-size="15"
          min-width="1080px"
          empty-text="暂无告警规则"
          @update:page="loadRules"
        >
          <template #cell-name="{ row }">
            <div class="small"><strong>{{ row.name }}</strong></div>
            <div class="tiny muted-2">{{ row.description || '无描述' }}</div>
          </template>
          <template #cell-scope="{ row }">
            <span class="tag" :class="row.node_id ? 'tag-primary' : 'tag-teal'">
              {{ row.node_id ? row.node_name : '全部节点' }}
            </span>
          </template>
          <template #cell-condition="{ row }">
            <span class="mono small">{{ row.metric_key }} {{ operatorText(row) }}</span>
          </template>
          <template #cell-duration_sec="{ row }">
            <span class="num small">{{ row.duration_sec ? `${row.duration_sec}s` : '立即' }}</span>
          </template>
          <template #cell-severity="{ row }">
            <span class="tag" :class="severityTone[row.severity]">{{ row.severity_label }}</span>
          </template>
          <template #cell-enabled="{ row }">
            <span class="tag" :class="row.enabled ? 'tag-online' : 'tag-offline'">{{ row.enabled ? '已启用' : '已停用' }}</span>
          </template>
          <template #cell-trigger_count="{ row }"><span class="num">{{ fmtNumber(row.trigger_count) }}</span></template>
          <template #cell-actions="{ row }">
            <div class="actions">
              <button v-if="userStore.canOperate" class="btn btn-sm" @click="openRuleForm(row)">
                <AppIcon name="edit" :size="13" />编辑
              </button>
              <button v-if="userStore.canOperate" class="btn btn-sm" @click="toggleRule(row)">
                {{ row.enabled ? '停用' : '启用' }}
              </button>
              <button v-if="userStore.canOperate" class="btn btn-sm btn-danger" @click="removeRule(row)">
                <AppIcon name="trash" :size="13" />
              </button>
            </div>
          </template>
        </DataTable>
      </div>
    </div>

    <!-- 规则表单 -->
    <AppModal
      v-model="showRuleForm"
      :title="editingRule ? `编辑规则 · ${editingRule.name}` : '新建告警规则'"
      size="lg"
      :loading="submitting"
      @confirm="submitRule"
    >
      <div class="form-grid">
        <div class="field span-2">
          <label class="field-label">规则名称<span class="req">*</span></label>
          <input v-model="ruleForm.name" class="input" placeholder="如 机房温度过高" />
        </div>
        <div class="field">
          <label class="field-label">监测指标<span class="req">*</span></label>
          <select v-model="ruleForm.metric_key" class="select">
            <option v-for="item in metrics" :key="item.metric_key" :value="item.metric_key">
              {{ item.name }}（{{ item.metric_key }}）
            </option>
          </select>
        </div>
        <div class="field">
          <label class="field-label">生效范围</label>
          <select v-model="ruleForm.node_id" class="select">
            <option :value="0">全部节点</option>
            <option v-for="node in nodes" :key="node.id" :value="node.id">{{ node.name }}</option>
          </select>
        </div>
        <div class="field">
          <label class="field-label">比较方式</label>
          <select v-model="ruleForm.operator" class="select">
            <option v-for="item in dicts.operators" :key="item.value" :value="item.value">{{ item.label }}</option>
          </select>
        </div>
        <div class="field">
          <label class="field-label">
            {{ ruleForm.operator === 'out_of_range' ? '下限值' : '阈值' }}
          </label>
          <input v-model.number="ruleForm.threshold" class="input" type="number" step="0.1" />
        </div>
        <div v-if="ruleForm.operator === 'out_of_range'" class="field">
          <label class="field-label">上限值</label>
          <input v-model.number="ruleForm.threshold2" class="input" type="number" step="0.1" />
        </div>
        <div class="field">
          <label class="field-label">持续时长（秒）</label>
          <input v-model.number="ruleForm.duration_sec" class="input" type="number" min="0" />
          <span class="field-hint">0 表示命中即刻告警；大于 0 需连续满足才触发，可抑制瞬时抖动</span>
        </div>
        <div class="field">
          <label class="field-label">告警级别</label>
          <select v-model="ruleForm.severity" class="select">
            <option v-for="item in dicts.severities" :key="item.value" :value="item.value">{{ item.label }}</option>
          </select>
        </div>
        <div class="field">
          <label class="field-label">静默期（秒）</label>
          <input v-model.number="ruleForm.silence_sec" class="input" type="number" min="0" />
          <span class="field-hint">静默期内重复命中只累加次数，不重复产生新告警</span>
        </div>
        <div class="field">
          <label class="field-label">启用状态</label>
          <select v-model="ruleForm.enabled" class="select">
            <option :value="true">启用</option>
            <option :value="false">停用</option>
          </select>
        </div>
        <div class="field span-2">
          <label class="field-label">规则说明</label>
          <input v-model="ruleForm.description" class="input" placeholder="选填" />
        </div>
      </div>
    </AppModal>
  </div>
</template>

<style scoped>
.stat {
  display: flex; align-items: center; gap: 13px;
  padding: 16px 18px; background: var(--c-surface);
  border: 1px solid var(--c-border); border-radius: var(--radius-lg);
  box-shadow: var(--shadow-sm);
}
.stat-icon {
  width: 40px; height: 40px; border-radius: 11px;
  display: flex; align-items: center; justify-content: center;
  color: var(--tone-color); background: var(--tone-bg);
}
.stat-label { font-size: 12.5px; color: var(--c-text-2); }
.stat-value { font-size: 23px; font-weight: 600; line-height: 1.2; }
.stat-value em { font-size: 12px; font-style: normal; color: var(--c-text-3); font-weight: 500; }
.tone-red { --tone-color: var(--c-red); --tone-bg: var(--c-red-100); }
.tone-amber { --tone-color: var(--c-amber); --tone-bg: var(--c-amber-100); }
.tone-primary { --tone-color: var(--c-primary); --tone-bg: var(--c-primary-100); }

.tabs { display: flex; gap: 4px; }
.tab {
  display: flex; align-items: center; gap: 6px;
  height: 32px; padding: 0 14px; border: none; border-radius: 8px;
  background: transparent; color: var(--c-text-2);
  font-family: inherit; font-size: 13px; cursor: pointer;
}
.tab.active { background: var(--c-primary-100); color: var(--c-primary-600); font-weight: 600; }
.filter-row { display: flex; align-items: center; gap: 9px; flex-wrap: wrap; }
.field-hint { font-size: 11.5px; color: var(--c-text-3); }
</style>
