<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { api, fmtTime, relativeTime } from '@/api'
import { useUserStore } from '@/stores/user'
import { useRealtimeStore } from '@/stores/realtime'
import { useToastStore } from '@/stores/toast'
import DataTable from '@/components/DataTable.vue'
import AppIcon from '@/components/AppIcon.vue'
import CommandDialog from '@/components/CommandDialog.vue'
import EmptyState from '@/components/EmptyState.vue'

const userStore = useUserStore()
const realtime = useRealtimeStore()
const toast = useToastStore()

const loading = ref(false)
const rows = ref([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(15)
const catalog = ref([])
const nodes = ref([])
const pending = ref({ pending: 0, sent: 0 })
const filters = reactive({ node_id: '', status: '', command: '' })

const showCommand = ref(false)
const commandTargets = ref([])
const detail = ref(null)
const showDetail = ref(false)

const columns = [
  { key: 'command_label', label: '指令', width: '140px' },
  { key: 'node_name', label: '目标节点', width: '200px' },
  { key: 'params', label: '参数', width: '200px' },
  { key: 'channel', label: '下发通道', width: '108px' },
  { key: 'status', label: '执行状态', width: '100px' },
  { key: 'issued_by', label: '下发人', width: '106px' },
  { key: 'issued_at', label: '下发时间', width: '165px' },
  { key: 'cost', label: '耗时', width: '88px', align: 'right' },
  { key: 'actions', label: '操作', width: '150px' }
]

const statusTone = {
  success: 'tag-online', failed: 'tag-critical', timeout: 'tag-major',
  sent: 'tag-warning', pending: 'tag-primary'
}

async function load() {
  loading.value = true
  try {
    const res = await api.commands.list({
      page: page.value,
      page_size: pageSize.value,
      node_id: filters.node_id || undefined,
      status: filters.status || undefined,
      command: filters.command || undefined
    })
    if (res.code === 0) {
      rows.value = res.data.items
      total.value = res.data.total
    }
    const countRes = await api.commands.pendingCount()
    if (countRes.code === 0) pending.value = countRes.data
  } finally {
    loading.value = false
  }
}

async function cancel(cmd) {
  if (!window.confirm(`确认取消指令「${cmd.command_label}」？`)) return
  const res = await api.commands.cancel(cmd.cmd_id)
  if (res.code === 0) { toast.success('指令已取消'); load() } else toast.error(res.message)
}

async function scanTimeout() {
  const res = await api.commands.scanTimeout()
  if (res.code === 0) { toast.success(res.message); load() }
}

function openCommand(nodesList) {
  commandTargets.value = nodesList
  showCommand.value = true
}

async function showCmdDetail(row) {
  const res = await api.commands.detail(row.cmd_id)
  if (res.code === 0) { detail.value = res.data; showDetail.value = true }
}

const costText = (row) => {
  if (!row.ack_at || !row.sent_at) return '—'
  const diff = (new Date(row.ack_at) - new Date(row.sent_at)) / 1000
  return diff >= 0 ? `${diff.toFixed(1)} s` : '—'
}

realtime.connect({
  // 页面级订阅
  onCommand: () => load()
}, 'commands')

onMounted(async () => {
  const [catRes, nodeRes] = await Promise.all([
    api.commands.catalog(), api.nodes.list({ page: 1, page_size: 100 })
  ])
  if (catRes.code === 0) catalog.value = catRes.data
  if (nodeRes.code === 0) nodes.value = nodeRes.data.items
  load()
})
</script>

<template>
  <div>
    <!-- 概览 -->
    <div class="grid-4 mb-16">
      <div class="stat tone-primary">
        <div class="stat-icon"><AppIcon name="command" :size="19" /></div>
        <div><div class="stat-label">指令总数</div><div class="stat-value">{{ total }}</div></div>
      </div>
      <div class="stat tone-amber">
        <div class="stat-icon"><AppIcon name="clock" :size="19" /></div>
        <div><div class="stat-label">待节点取走</div><div class="stat-value">{{ pending.pending }}</div></div>
      </div>
      <div class="stat tone-teal">
        <div class="stat-icon"><AppIcon name="radio" :size="19" /></div>
        <div><div class="stat-label">已下发待回执</div><div class="stat-value">{{ pending.sent }}</div></div>
      </div>
      <div class="stat tone-green">
        <div class="stat-icon"><AppIcon name="check-circle" :size="19" /></div>
        <div>
          <div class="stat-label">执行成功率</div>
          <div class="stat-value">
            {{ total ? Math.round((rows.filter((r) => r.status === 'success').length / rows.length || 0) * 100) : 0 }}<em>%（当前页）</em>
          </div>
        </div>
      </div>
    </div>

    <!-- 指令面板 -->
    <div class="card mb-16">
      <div class="card-head">
        <div class="card-title"><i class="bar" />可用指令集</div>
        <span class="muted small">点击指令卡片即可向节点下发</span>
      </div>
      <div class="card-body">
        <div class="cmd-grid">
          <button
            v-for="item in catalog"
            :key="item.command"
            class="cmd-card"
            :disabled="!userStore.canOperate"
            @click="openCommand([])"
          >
            <div class="cmd-icon">
              <AppIcon :name="item.command === 'capture_image' ? 'camera'
                : item.command === 'start_record' ? 'video'
                : item.command === 'stop_record' ? 'stop'
                : item.command === 'set_interval' ? 'clock'
                : item.command === 'sync_config' ? 'sync'
                : item.command === 'self_test' ? 'shield' : 'power'" :size="19" />
            </div>
            <div class="cmd-name">{{ item.label }}</div>
            <div class="cmd-desc">{{ item.desc }}</div>
            <div class="cmd-code mono tiny">{{ item.command }}</div>
          </button>
        </div>

        <div class="quick-bar mt-16">
          <span class="small muted">快捷操作：</span>
          <select
            class="select"
            style="width: 220px"
            @change="(e) => { if (e.target.value) openCommand(nodes.filter((n) => n.id === Number(e.target.value))); e.target.value = '' }"
          >
            <option value="">选择节点下发指令…</option>
            <option v-for="node in nodes" :key="node.id" :value="node.id">{{ node.name }}</option>
          </select>
          <button class="btn" @click="openCommand(nodes.filter((n) => n.status === 'online'))">
            <AppIcon name="radio" :size="14" />向全部在线节点下发
          </button>
        </div>
      </div>
    </div>

    <!-- 指令历史 -->
    <div class="card">
      <div class="card-head">
        <div class="card-title"><i class="bar" />指令下发记录</div>
        <div class="row gap-8">
          <select v-model="filters.command" class="select" style="width: 150px" @change="page = 1; load()">
            <option value="">全部指令</option>
            <option v-for="item in catalog" :key="item.command" :value="item.command">{{ item.label }}</option>
          </select>
          <select v-model="filters.status" class="select" style="width: 130px" @change="page = 1; load()">
            <option value="">全部状态</option>
            <option value="pending">待下发</option>
            <option value="sent">已下发</option>
            <option value="success">执行成功</option>
            <option value="failed">执行失败</option>
            <option value="timeout">已超时</option>
          </select>
          <button v-if="userStore.canOperate" class="btn btn-sm" @click="scanTimeout">
            <AppIcon name="clock" :size="14" />超时巡检
          </button>
          <button class="btn btn-sm" @click="load"><AppIcon name="refresh" :size="14" />刷新</button>
        </div>
      </div>
      <div class="card-body flush">
        <DataTable
          v-model:page="page"
          :columns="columns"
          :rows="rows"
          :loading="loading"
          :total="total"
          :page-size="pageSize"
          min-width="1180px"
          empty-text="暂无指令记录"
          @update:page="load"
        >
          <template #cell-command_label="{ row }">
            <div class="row gap-6">
              <AppIcon :name="row.command === 'capture_image' ? 'camera'
                : row.command === 'start_record' ? 'video'
                : row.command === 'stop_record' ? 'stop'
                : row.command === 'set_interval' ? 'clock'
                : row.command === 'sync_config' ? 'sync'
                : row.command === 'self_test' ? 'shield' : 'power'" :size="15" />
              <span class="small">{{ row.command_label }}</span>
            </div>
            <div class="tiny muted-2 mono">{{ row.cmd_id.slice(0, 14) }}…</div>
          </template>
          <template #cell-node_name="{ row }">
            <router-link :to="`/nodes/${row.node_id}`" class="small">{{ row.node_name }}</router-link>
            <div class="tiny muted-2 mono">{{ row.node_uid }}</div>
          </template>
          <template #cell-params="{ row }">
            <span class="mono tiny">{{ Object.keys(row.params || {}).length ? JSON.stringify(row.params) : '—' }}</span>
          </template>
          <template #cell-channel="{ row }">
            <span class="tag" :class="row.channel === 'mqtt' ? 'tag-teal' : 'tag-primary'">
              {{ row.channel === 'mqtt' ? 'MQTT 实时' : 'HTTP 轮询' }}
            </span>
          </template>
          <template #cell-status="{ row }">
            <span class="tag" :class="statusTone[row.status] || 'tag'">{{ row.status_label }}</span>
          </template>
          <template #cell-issued_at="{ row }">
            <div class="small mono">{{ fmtTime(row.issued_at) }}</div>
            <div class="tiny muted-2">{{ relativeTime(row.issued_at) }}</div>
          </template>
          <template #cell-cost="{ row }"><span class="num small">{{ costText(row) }}</span></template>
          <template #cell-actions="{ row }">
            <div class="actions">
              <button class="btn btn-sm" @click="showCmdDetail(row)"><AppIcon name="eye" :size="13" />回执</button>
              <button
                v-if="userStore.canOperate && ['pending', 'sent'].includes(row.status)"
                class="btn btn-sm btn-danger"
                @click="cancel(row)"
              >取消</button>
            </div>
          </template>
        </DataTable>
      </div>
    </div>

    <CommandDialog v-model="showCommand" :nodes="commandTargets" @issued="load" />

    <!-- 回执详情 -->
    <AppModal v-model="showDetail" title="指令执行回执" :hide-footer="true" size="lg">
      <div v-if="detail">
        <div class="detail-head">
          <span class="tag" :class="statusTone[detail.status] || 'tag'">{{ detail.status_label }}</span>
          <strong>{{ detail.command_label }}</strong>
          <span class="muted small">{{ detail.node_name }}</span>
        </div>
        <div class="form-grid mt-16">
          <div class="field"><label class="field-label">指令 ID</label><div class="readonly mono">{{ detail.cmd_id }}</div></div>
          <div class="field"><label class="field-label">下发通道</label><div class="readonly">{{ detail.channel === 'mqtt' ? 'MQTT 实时下发' : 'HTTP 轮询取指令' }}</div></div>
          <div class="field"><label class="field-label">下发人</label><div class="readonly">{{ detail.issued_by || '—' }}</div></div>
          <div class="field"><label class="field-label">下发时间</label><div class="readonly mono">{{ fmtTime(detail.issued_at) }}</div></div>
          <div class="field"><label class="field-label">发送时间</label><div class="readonly mono">{{ fmtTime(detail.sent_at) }}</div></div>
          <div class="field"><label class="field-label">回执时间</label><div class="readonly mono">{{ fmtTime(detail.ack_at) }}</div></div>
        </div>
        <div class="mt-16">
          <div class="field-label mb-10">指令参数</div>
          <pre class="code-block">{{ JSON.stringify(detail.params || {}, null, 2) }}</pre>
        </div>
        <div class="mt-16">
          <div class="field-label mb-10">节点回执</div>
          <pre class="code-block">{{ JSON.stringify(detail.result || {}, null, 2) }}</pre>
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
.stat-value em { font-size: 11.5px; font-style: normal; color: var(--c-text-3); font-weight: 500; }
.tone-primary { --tone-color: var(--c-primary); --tone-bg: var(--c-primary-100); }
.tone-amber { --tone-color: var(--c-amber); --tone-bg: var(--c-amber-100); }
.tone-teal { --tone-color: var(--c-teal); --tone-bg: var(--c-teal-100); }
.tone-green { --tone-color: var(--c-green); --tone-bg: var(--c-green-100); }

.cmd-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(200px, 1fr)); gap: 12px; }
.cmd-card {
  display: flex; flex-direction: column; align-items: flex-start; gap: 5px;
  padding: 14px 15px; text-align: left;
  border: 1px solid var(--c-border); border-radius: 11px;
  background: var(--c-surface); cursor: pointer; font-family: inherit;
  transition: all 0.16s;
}
.cmd-card:hover:not(:disabled) { border-color: var(--c-primary); background: var(--c-primary-50); transform: translateY(-2px); box-shadow: var(--shadow); }
.cmd-card:disabled { opacity: 0.6; cursor: not-allowed; }
.cmd-icon {
  width: 36px; height: 36px; border-radius: 10px;
  display: flex; align-items: center; justify-content: center;
  background: var(--c-primary-100); color: var(--c-primary-600);
}
.cmd-name { font-size: 13.5px; font-weight: 600; }
.cmd-desc { font-size: 11.5px; color: var(--c-text-3); line-height: 1.5; }
.cmd-code { color: var(--c-text-3); }

.quick-bar {
  display: flex; align-items: center; gap: 10px; flex-wrap: wrap;
  padding: 12px 14px; border-radius: 10px;
  background: var(--c-surface-2); border: 1px dashed var(--c-border-strong);
}

.detail-head { display: flex; align-items: center; gap: 10px; }
.readonly {
  padding: 7px 11px; border-radius: 7px;
  background: var(--c-surface-2); border: 1px solid var(--c-border);
  font-size: 12.5px; min-height: 34px; display: flex; align-items: center;
}
.code-block {
  margin: 0; padding: 13px 15px; border-radius: 9px;
  background: #0F2A44; color: #B9DDF5;
  font-family: var(--font-mono); font-size: 12px; line-height: 1.65;
  max-height: 260px; overflow: auto; white-space: pre-wrap; word-break: break-all;
}
</style>
