<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { api, fmtNumber, fmtTime, relativeTime } from '@/api'
import { useUserStore } from '@/stores/user'
import { useToastStore } from '@/stores/toast'
import DataTable from '@/components/DataTable.vue'
import AppModal from '@/components/AppModal.vue'
import AppIcon from '@/components/AppIcon.vue'
import StatusTag from '@/components/StatusTag.vue'
import CommandDialog from '@/components/CommandDialog.vue'

const userStore = useUserStore()
const toast = useToastStore()

const loading = ref(false)
const rows = ref([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(12)
const selected = ref([])
const specs = ref({ node_types: [], statuses: [] })
const groups = ref([])

const filters = reactive({ keyword: '', status: '', node_type: '', group_id: '' })

const showForm = ref(false)
const editing = ref(null)
const form = reactive({
  node_uid: '', name: '', node_type: 'raspberrypi', model: '', serial_no: '',
  group_id: 0, ip_address: '', mac_address: '', location: '', os_version: '',
  report_interval: 60, remark: '', capabilities: { camera: true, video: true, sensors: [] },
  sensorText: 'temperature,humidity'
})
const submitting = ref(false)

const credential = ref(null)
const showCredential = ref(false)
const showCommand = ref(false)
const commandTargets = ref([])
const showGroups = ref(false)
const newGroup = reactive({ name: '', code: '', description: '' })

const columns = computed(() => [
  { key: 'name', label: '节点名称', width: '210px' },
  { key: 'node_type', label: '类型', width: '110px' },
  { key: 'group_name', label: '分组', width: '120px' },
  { key: 'status', label: '状态', width: '92px' },
  { key: 'ip_address', label: 'IP 地址', width: '126px' },
  { key: 'resource', label: '资源占用', width: '190px' },
  { key: 'report_interval', label: '上报周期', width: '88px', align: 'right' },
  { key: 'last_seen_at', label: '最后在线', width: '112px' },
  { key: 'actions', label: '操作', width: '210px' }
])

async function load() {
  loading.value = true
  try {
    const res = await api.nodes.list({
      page: page.value,
      page_size: pageSize.value,
      keyword: filters.keyword || undefined,
      status: filters.status || undefined,
      node_type: filters.node_type || undefined,
      group_id: filters.group_id || undefined
    })
    if (res.code === 0) {
      rows.value = res.data.items
      total.value = res.data.total
    }
  } finally {
    loading.value = false
  }
}

async function loadMeta() {
  const [specRes, groupRes] = await Promise.all([api.nodes.specs(), api.nodes.groups()])
  if (specRes.code === 0) specs.value = specRes.data
  if (groupRes.code === 0) groups.value = groupRes.data
}

function search() { page.value = 1; load() }
function reset() {
  filters.keyword = ''
  filters.status = ''
  filters.node_type = ''
  filters.group_id = ''
  page.value = 1
  load()
}

function openCreate() {
  editing.value = null
  Object.assign(form, {
    node_uid: '', name: '', node_type: 'raspberrypi', model: '', serial_no: '',
    group_id: groups.value[0]?.id || 0, ip_address: '', mac_address: '', location: '',
    os_version: '', report_interval: 60, remark: '',
    capabilities: { camera: true, video: true, sensors: [] },
    sensorText: 'temperature,humidity'
  })
  showForm.value = true
}

function openEdit(row) {
  editing.value = row
  Object.assign(form, {
    node_uid: row.node_uid,
    name: row.name,
    node_type: row.node_type,
    model: row.model || '',
    serial_no: row.serial_no || '',
    group_id: row.group_id || 0,
    ip_address: row.ip_address || '',
    mac_address: row.mac_address || '',
    location: row.location || '',
    os_version: row.os_version || '',
    report_interval: row.report_interval || 60,
    remark: row.remark || '',
    capabilities: { camera: true, video: true, ...(row.capabilities || {}) },
    sensorText: (row.capabilities?.sensors || []).join(',')
  })
  showForm.value = true
}

async function submitForm() {
  if (!form.node_uid.trim() || !form.name.trim()) {
    toast.warning('请填写节点编码与名称')
    return
  }
  submitting.value = true
  const payload = {
    node_uid: form.node_uid.trim(),
    name: form.name.trim(),
    node_type: form.node_type,
    model: form.model,
    serial_no: form.serial_no,
    group_id: Number(form.group_id) || 0,
    ip_address: form.ip_address,
    mac_address: form.mac_address,
    location: form.location,
    os_version: form.os_version,
    report_interval: Number(form.report_interval) || 60,
    remark: form.remark,
    capabilities: {
      ...form.capabilities,
      sensors: form.sensorText.split(',').map((item) => item.trim()).filter(Boolean)
    }
  }
  try {
    const res = editing.value
      ? await api.nodes.update(editing.value.id, payload)
      : await api.nodes.create(payload)
    if (res.code === 0) {
      toast.success(res.message)
      showForm.value = false
      if (!editing.value && res.data.credential) {
        credential.value = { ...res.data.credential, node_uid: payload.node_uid, isNew: true }
        showCredential.value = true
      }
      load()
    } else {
      toast.error(res.message)
    }
  } finally {
    submitting.value = false
  }
}

async function toggleNode(row) {
  const res = await api.nodes.toggle(row.id)
  if (res.code === 0) { toast.success(res.message); load() } else toast.error(res.message)
}

async function removeNode(row) {
  if (!window.confirm(`确认删除节点「${row.name}」？\n该操作会同时删除其遥测数据、媒体记录与告警历史，且不可恢复。`)) return
  const res = await api.nodes.remove(row.id)
  if (res.code === 0) { toast.success('节点已删除'); load() } else toast.error(res.message)
}

async function resetCredential(row) {
  if (!window.confirm(`确认为「${row.name}」重置接入凭证？\n重置后原凭证立即失效，节点需更新配置后才能继续上报。`)) return
  const res = await api.nodes.resetCredential(row.id)
  if (res.code === 0) {
    credential.value = { ...res.data, node_uid: row.node_uid, isNew: true }
    showCredential.value = true
    load()
  } else toast.error(res.message)
}

function openCommand(nodes) {
  commandTargets.value = Array.isArray(nodes) ? nodes : [nodes]
  showCommand.value = true
}

function batchCommand() {
  const targets = rows.value.filter((row) => selected.value.includes(row.id))
  if (!targets.length) { toast.warning('请先勾选目标节点'); return }
  openCommand(targets)
}

async function copyText(text) {
  try {
    await navigator.clipboard.writeText(text)
    toast.success('已复制到剪贴板')
  } catch (e) {
    toast.warning('浏览器拒绝访问剪贴板，请手动选择复制')
  }
}

/** 生成边缘节点配置片段（供展示与一键复制复用同一份内容） */
const credentialConfig = computed(() => {
  const c = credential.value
  if (!c) return ''
  return [
    'node:',
    `  node_uid: "${c.node_uid}"`,
    `  access_key: "${c.access_key}"`,
    `  secret: "${c.secret}"`,
    '',
    'server:',
    '  base_url: "http://<平台地址>:5000"'
  ].join('\n')
})

async function createGroup() {
  if (!newGroup.name.trim()) { toast.warning('请填写分组名称'); return }
  const res = await api.nodes.createGroup({ ...newGroup })
  if (res.code === 0) {
    toast.success('分组已创建')
    newGroup.name = ''; newGroup.code = ''; newGroup.description = ''
    loadMeta()
  } else toast.error(res.message)
}

async function removeGroup(group) {
  if (!window.confirm(`确认删除分组「${group.name}」？`)) return
  const res = await api.nodes.removeGroup(group.id)
  if (res.code === 0) { toast.success('分组已删除'); loadMeta() } else toast.error(res.message)
}

function resourceTone(value) {
  const num = Number(value) || 0
  if (num >= 85) return 'danger'
  if (num >= 65) return 'warn'
  return 'ok'
}

onMounted(async () => {
  await loadMeta()
  load()
})
</script>

<template>
  <div>
    <!-- 筛选栏 -->
    <div class="card mb-16">
      <div class="card-body tight">
        <div class="toolbar">
          <div class="search-box">
            <AppIcon name="search" :size="16" />
            <input
              v-model="filters.keyword"
              class="search-input"
              placeholder="搜索节点名称 / 编码 / 位置 / IP"
              @keyup.enter="search"
            />
          </div>
          <select v-model="filters.status" class="select" style="width: 128px" @change="search">
            <option value="">全部状态</option>
            <option v-for="item in specs.statuses" :key="item.value" :value="item.value">{{ item.label }}</option>
          </select>
          <select v-model="filters.node_type" class="select" style="width: 150px" @change="search">
            <option value="">全部类型</option>
            <option v-for="item in specs.node_types" :key="item.value" :value="item.value">{{ item.label }}</option>
          </select>
          <select v-model="filters.group_id" class="select" style="width: 140px" @change="search">
            <option value="">全部分组</option>
            <option v-for="item in groups" :key="item.id" :value="item.id">{{ item.name }}</option>
          </select>
          <button class="btn" @click="search"><AppIcon name="search" :size="15" />查询</button>
          <button class="btn btn-ghost" @click="reset">重置</button>
          <div class="grow" />
          <button class="btn" @click="showGroups = true"><AppIcon name="layers" :size="15" />分组管理</button>
          <button v-if="selected.length" class="btn" @click="batchCommand">
            <AppIcon name="command" :size="15" />批量指令（{{ selected.length }}）
          </button>
          <button class="btn" @click="load"><AppIcon name="refresh" :size="15" />刷新</button>
          <button v-if="userStore.canOperate" class="btn btn-primary" @click="openCreate">
            <AppIcon name="plus" :size="15" />新建节点
          </button>
        </div>
      </div>
    </div>

    <!-- 节点表格 -->
    <div class="card">
      <div class="card-head">
        <div class="card-title"><i class="bar" />边缘节点清单</div>
        <span class="muted small">共 {{ total }} 个节点</span>
      </div>
      <div class="card-body flush">
        <DataTable
          v-model:page="page"
          v-model:selected="selected"
          :columns="columns"
          :rows="rows"
          :loading="loading"
          :total="total"
          :page-size="pageSize"
          selectable
          min-width="1180px"
          empty-text="暂无节点，点击右上角「新建节点」开始接入"
          @update:page="load"
        >
          <template #cell-name="{ row }">
            <router-link :to="`/nodes/${row.id}`" class="node-name">{{ row.name }}</router-link>
            <div class="tiny muted-2 mono">{{ row.node_uid }}</div>
          </template>
          <template #cell-node_type="{ row }">
            <span class="tag tag-primary">{{ row.node_type_label }}</span>
          </template>
          <template #cell-group_name="{ row }">
            <span class="small">{{ row.group_name }}</span>
          </template>
          <template #cell-status="{ row }">
            <StatusTag :status="row.status" :label="row.status_label" />
          </template>
          <template #cell-ip_address="{ row }">
            <span class="mono small">{{ row.ip_address || '—' }}</span>
          </template>
          <template #cell-resource="{ row }">
            <div class="res-bars">
              <div class="res-item">
                <span class="res-label">CPU</span>
                <div class="res-track"><div class="res-fill" :class="resourceTone(row.cpu_percent)" :style="{ width: `${Math.min(row.cpu_percent, 100)}%` }" /></div>
                <span class="res-val mono">{{ (row.cpu_percent ?? 0).toFixed(0) }}%</span>
              </div>
              <div class="res-item">
                <span class="res-label">内存</span>
                <div class="res-track"><div class="res-fill" :class="resourceTone(row.mem_percent)" :style="{ width: `${Math.min(row.mem_percent, 100)}%` }" /></div>
                <span class="res-val mono">{{ (row.mem_percent ?? 0).toFixed(0) }}%</span>
              </div>
              <div class="res-item">
                <span class="res-label">温度</span>
                <div class="res-track"><div class="res-fill" :class="resourceTone(row.cpu_temp * 1.15)" :style="{ width: `${Math.min((row.cpu_temp ?? 0) / 90 * 100, 100)}%` }" /></div>
                <span class="res-val mono">{{ (row.cpu_temp ?? 0).toFixed(0) }}℃</span>
              </div>
            </div>
          </template>
          <template #cell-report_interval="{ row }">
            <span class="mono small">{{ row.report_interval }}s</span>
          </template>
          <template #cell-last_seen_at="{ row }">
            <span class="small" :title="fmtTime(row.last_seen_at)">{{ relativeTime(row.last_seen_at) }}</span>
          </template>
          <template #cell-actions="{ row }">
            <div class="actions">
              <router-link class="btn btn-sm" :to="`/nodes/${row.id}`">
                <AppIcon name="eye" :size="13" />详情
              </router-link>
              <button v-if="userStore.canOperate" class="btn btn-sm" @click="openCommand(row)">
                <AppIcon name="command" :size="13" />指令
              </button>
              <button v-if="userStore.canOperate" class="btn btn-sm" @click="openEdit(row)">
                <AppIcon name="edit" :size="13" />编辑
              </button>
              <button v-if="userStore.canOperate" class="btn btn-sm" @click="resetCredential(row)">凭证</button>
              <button
                v-if="userStore.canOperate"
                class="btn btn-sm"
                @click="toggleNode(row)"
              >{{ row.enabled ? '停用' : '启用' }}</button>
              <button v-if="userStore.isAdmin" class="btn btn-sm btn-danger" @click="removeNode(row)">
                <AppIcon name="trash" :size="13" />
              </button>
            </div>
          </template>
        </DataTable>
      </div>
    </div>

    <!-- 新建 / 编辑节点 -->
    <AppModal
      v-model="showForm"
      :title="editing ? `编辑节点 · ${editing.name}` : '新建边缘节点'"
      size="lg"
      :loading="submitting"
      @confirm="submitForm"
    >
      <div class="form-grid">
        <div class="field">
          <label class="field-label">节点编码<span class="req">*</span></label>
          <input v-model="form.node_uid" class="input" placeholder="如 RPI-LAB-A01" :disabled="!!editing" />
          <span class="field-hint">节点唯一标识，MQTT ClientID 与 HTTP 接入均以此为凭据标识</span>
        </div>
        <div class="field">
          <label class="field-label">节点名称<span class="req">*</span></label>
          <input v-model="form.name" class="input" placeholder="如 实验楼A区-图像采集节点" />
        </div>
        <div class="field">
          <label class="field-label">节点类型</label>
          <select v-model="form.node_type" class="select">
            <option v-for="item in specs.node_types" :key="item.value" :value="item.value">{{ item.label }}</option>
          </select>
        </div>
        <div class="field">
          <label class="field-label">所属分组</label>
          <select v-model="form.group_id" class="select">
            <option :value="0">未分组</option>
            <option v-for="item in groups" :key="item.id" :value="item.id">{{ item.name }}</option>
          </select>
        </div>
        <div class="field">
          <label class="field-label">硬件型号</label>
          <input v-model="form.model" class="input" placeholder="如 Raspberry Pi 4B 8GB" />
        </div>
        <div class="field">
          <label class="field-label">序列号</label>
          <input v-model="form.serial_no" class="input" placeholder="选填" />
        </div>
        <div class="field">
          <label class="field-label">部署位置</label>
          <input v-model="form.location" class="input" placeholder="如 实验楼A区 305 机房" />
        </div>
        <div class="field">
          <label class="field-label">上报周期（秒）</label>
          <input v-model.number="form.report_interval" class="input" type="number" min="5" />
        </div>
        <div class="field">
          <label class="field-label">IP 地址</label>
          <input v-model="form.ip_address" class="input" placeholder="节点上线后会自动补全" />
        </div>
        <div class="field">
          <label class="field-label">MAC 地址</label>
          <input v-model="form.mac_address" class="input" placeholder="选填" />
        </div>
        <div class="field span-2">
          <label class="field-label">传感器指标（英文逗号分隔）</label>
          <input v-model="form.sensorText" class="input" placeholder="temperature,humidity,co2_ppm" />
        </div>
        <div class="field span-2">
          <label class="field-label">备注</label>
          <textarea v-model="form.remark" class="textarea" placeholder="选填，如安装位置、责任人" />
        </div>
      </div>

      <div class="cap-row">
        <label class="cap-item">
          <input v-model="form.capabilities.camera" type="checkbox" />
          <span><AppIcon name="camera" :size="15" />摄像头抓拍</span>
        </label>
        <label class="cap-item">
          <input v-model="form.capabilities.video" type="checkbox" />
          <span><AppIcon name="video" :size="15" />视频录制</span>
        </label>
      </div>

      <div v-if="!editing" class="tip mt-16">
        <AppIcon name="key" :size="15" />
        <div>创建成功后平台会一次性签发接入凭证（Access Key / Secret），请立即写入节点 Agent 配置。</div>
      </div>
    </AppModal>

    <!-- 凭证展示 -->
    <AppModal v-model="showCredential" title="节点接入凭证" :hide-footer="true" size="lg">
      <div v-if="credential">
        <div class="warn-box">
          <AppIcon name="alert-circle" :size="16" />
          <div>Secret 仅在本次显示，关闭后无法再次查看。若遗失请点击「重置凭证」重新签发。</div>
        </div>
        <div class="cred-grid mt-16">
          <div class="cred-item">
            <div class="cred-label">节点编码</div>
            <div class="cred-value mono">{{ credential.node_uid }}</div>
          </div>
          <div class="cred-item">
            <div class="cred-label">X-Node-Key（Access Key）</div>
            <div class="cred-value mono">{{ credential.access_key }}</div>
            <button class="btn btn-sm" @click="copyText(credential.access_key)"><AppIcon name="copy" :size="13" />复制</button>
          </div>
          <div class="cred-item">
            <div class="cred-label">X-Node-Secret</div>
            <div class="cred-value mono accent">{{ credential.secret }}</div>
            <button class="btn btn-sm" @click="copyText(credential.secret)"><AppIcon name="copy" :size="13" />复制</button>
          </div>
        </div>
        <div class="mt-16">
          <div class="field-label mb-10">节点 Agent 配置片段（config.yaml）</div>
          <pre class="code-block">{{ credentialConfig }}</pre>
          <button
            class="btn btn-sm mt-10"
            @click="copyText(credentialConfig)"
          ><AppIcon name="copy" :size="13" />复制配置片段</button>
        </div>
      </div>
    </AppModal>

    <!-- 分组管理 -->
    <AppModal v-model="showGroups" title="节点分组管理" :hide-footer="true">
      <div class="group-form">
        <input v-model="newGroup.name" class="input" placeholder="分组名称，如 实验楼 A 区" />
        <input v-model="newGroup.code" class="input" style="max-width: 130px" placeholder="编码" />
        <button class="btn btn-primary" @click="createGroup"><AppIcon name="plus" :size="15" />添加</button>
      </div>
      <input v-model="newGroup.description" class="input mt-10" placeholder="分组描述（选填）" />
      <div class="group-list mt-16">
        <div v-for="group in groups" :key="group.id" class="group-row">
          <div class="grow">
            <div class="small"><strong>{{ group.name }}</strong>
              <span class="tag tag-primary" style="margin-left: 8px">{{ group.node_count }} 个节点</span>
            </div>
            <div class="tiny muted-2">{{ group.description || '无描述' }}</div>
          </div>
          <button class="btn btn-sm btn-danger" @click="removeGroup(group)">
            <AppIcon name="trash" :size="13" />
          </button>
        </div>
      </div>
    </AppModal>

    <CommandDialog v-model="showCommand" :nodes="commandTargets" @issued="load" />
  </div>
</template>

<style scoped>
.toolbar { display: flex; align-items: center; gap: 9px; flex-wrap: wrap; }
.search-box {
  display: flex; align-items: center; gap: 7px;
  height: 34px; padding: 0 11px; min-width: 270px;
  border: 1px solid var(--c-border-strong); border-radius: var(--radius-sm);
  background: var(--c-surface); color: var(--c-text-3);
}
.search-box:focus-within { border-color: var(--c-primary); box-shadow: 0 0 0 3px var(--c-primary-100); }
.search-input {
  flex: 1; border: none; outline: none; background: transparent;
  font-family: inherit; font-size: 13px; color: var(--c-text); min-width: 0;
}

.node-name { font-weight: 500; }
.res-bars { display: flex; flex-direction: column; gap: 3px; }
.res-item { display: flex; align-items: center; gap: 6px; }
.res-label { width: 30px; font-size: 11px; color: var(--c-text-3); }
.res-track { flex: 1; height: 5px; min-width: 54px; border-radius: 3px; background: var(--c-surface-3); overflow: hidden; }
.res-fill { height: 100%; border-radius: 3px; transition: width 0.3s; }
.res-fill.ok { background: linear-gradient(90deg, #5CC79A, #23A06B); }
.res-fill.warn { background: linear-gradient(90deg, #F0BD6A, #DE8A1B); }
.res-fill.danger { background: linear-gradient(90deg, #EC8B8B, #D34848); }
.res-val { width: 36px; text-align: right; font-size: 11px; color: var(--c-text-2); }

.field-hint { font-size: 11.5px; color: var(--c-text-3); line-height: 1.5; }

.cap-row { display: flex; gap: 20px; margin-top: 16px; padding-top: 14px; border-top: 1px dashed var(--c-border); }
.cap-item { display: flex; align-items: center; gap: 7px; cursor: pointer; font-size: 13px; }
.cap-item input { width: 15px; height: 15px; accent-color: var(--c-primary); }
.cap-item span { display: flex; align-items: center; gap: 5px; color: var(--c-text-2); }

.warn-box {
  display: flex; gap: 9px; padding: 11px 13px;
  border-radius: 9px; background: var(--c-amber-100); color: #8A5A0C;
  font-size: 12.5px; line-height: 1.6;
}
.cred-grid { display: flex; flex-direction: column; gap: 11px; }
.cred-item {
  display: flex; align-items: center; gap: 12px;
  padding: 11px 14px; border-radius: 9px;
  background: var(--c-surface-2); border: 1px solid var(--c-border);
}
.cred-label { width: 168px; font-size: 12.5px; color: var(--c-text-2); flex-shrink: 0; }
.cred-value { flex: 1; font-size: 13px; word-break: break-all; }
.cred-value.accent { color: var(--c-primary-600); font-weight: 600; }

.code-block {
  margin: 0; padding: 14px 16px;
  background: #0F2A44; color: #B9DDF5;
  border-radius: 10px; font-family: var(--font-mono); font-size: 12.5px;
  line-height: 1.75; overflow-x: auto; white-space: pre;
}
.tip {
  display: flex; gap: 9px; padding: 11px 13px; border-radius: 9px;
  background: var(--c-surface-2); border: 1px dashed var(--c-border-strong);
  font-size: 12.5px; color: var(--c-text-2);
}

.group-form { display: flex; gap: 9px; }
.group-list { display: flex; flex-direction: column; gap: 8px; }
.group-row {
  display: flex; align-items: center; gap: 12px;
  padding: 11px 14px; border-radius: 9px;
  background: var(--c-surface-2); border: 1px solid var(--c-border);
}
</style>
