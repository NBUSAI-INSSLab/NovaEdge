<script setup>
import { computed, onMounted, onUnmounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api, fmtBytes, fmtNumber, fmtTime, mediaUrl } from '@/api'
import { useUserStore } from '@/stores/user'
import { useRealtimeStore } from '@/stores/realtime'
import { useChartColors } from '@/utils/chartPalette'
import { useToastStore } from '@/stores/toast'
import EChart from '@/components/EChart.vue'
import AppIcon from '@/components/AppIcon.vue'
import AppModal from '@/components/AppModal.vue'
import EmptyState from '@/components/EmptyState.vue'

const route = useRoute()
const router = useRouter()
const userStore = useUserStore()
const realtime = useRealtimeStore()
const chartC = useChartColors()
const toast = useToastStore()

const loading = ref(true)
const items = ref([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(24)
const selected = ref([])
const nodes = ref([])
const statistics = ref(null)
const viewMode = ref('grid')

const filters = reactive({ node_id: '', file_type: '', keyword: '', start: '', end: '' })

const preview = ref(null)        // 当前预览的媒体对象
const showDetail = ref(false)
const editingTags = ref('')
const editingRemark = ref('')

const columns = [
  { key: 'file_name', label: '文件名' },
  { key: 'file_type', label: '类型', width: '92px' },
  { key: 'node_name', label: '来源节点', width: '190px' },
  { key: 'file_size_human', label: '大小', width: '100px', align: 'right' },
  { key: 'dimension', label: '分辨率/时长', width: '150px' },
  { key: 'captured_at', label: '采集时间', width: '165px' },
  { key: 'actions', label: '操作', width: '150px' }
]

async function load() {
  loading.value = true
  try {
    const res = await api.media.list({
      page: page.value,
      page_size: pageSize.value,
      node_id: filters.node_id || undefined,
      file_type: filters.file_type || undefined,
      keyword: filters.keyword || undefined,
      start: filters.start || undefined,
      end: filters.end || undefined
    })
    if (res.code === 0) {
      items.value = res.data.items
      total.value = res.data.total
    }
  } finally {
    loading.value = false
  }
}

async function loadMeta() {
  const [nodeRes, statRes] = await Promise.all([api.nodes.list({ page: 1, page_size: 100 }), api.media.statistics()])
  if (nodeRes.code === 0) nodes.value = nodeRes.data.items
  if (statRes.code === 0) statistics.value = statRes.data
}

function search() { page.value = 1; load() }
function reset() {
  filters.node_id = ''
  filters.file_type = ''
  filters.keyword = ''
  filters.start = ''
  filters.end = ''
  search()
}

function openPreview(item) {
  preview.value = item
  editingTags.value = (item.tags || []).join(',')
  editingRemark.value = item.remark || ''
}

async function saveMeta() {
  if (!preview.value) return
  const res = await api.media.update(preview.value.id, {
    tags: editingTags.value.split(',').map((t) => t.trim()).filter(Boolean),
    remark: editingRemark.value
  })
  if (res.code === 0) {
    toast.success('媒体信息已更新')
    load()
  }
}

function download(item) {
  // 通过携带令牌的地址触发浏览器下载（<a> 无法自定义请求头）
  window.open(mediaUrl(`/api/v1/media/${item.id}/download`), '_blank')
}

async function removeOne(item) {
  if (!window.confirm(`确认删除「${item.file_name}」？\n物理文件将从存储中移除，操作不可恢复。`)) return
  const res = await api.media.remove(item.id)
  if (res.code === 0) {
    toast.success('已删除')
    preview.value = null
    loadMeta()
    load()
  }
}

async function removeSelected() {
  if (!selected.value.length) { toast.warning('请先勾选要删除的文件'); return }
  if (!window.confirm(`确认删除选中的 ${selected.value.length} 个文件？`)) return
  const res = await api.media.batchDelete(selected.value)
  if (res.code === 0) {
    toast.success(res.message)
    selected.value = []
    loadMeta()
    load()
  }
}

function toggleSelect(item) {
  const index = selected.value.indexOf(item.id)
  if (index >= 0) selected.value.splice(index, 1)
  else selected.value.push(item.id)
}

const statCards = computed(() => statistics.value ? [
  { label: '媒体总数', value: fmtNumber(statistics.value.total), unit: '个', icon: 'media', tone: 'primary' },
  { label: '图片', value: fmtNumber(statistics.value.images), unit: '张', icon: 'image', tone: 'teal' },
  { label: '视频', value: fmtNumber(statistics.value.videos), unit: '段', icon: 'film', tone: 'purple' },
  { label: '存储占用', value: statistics.value.storage_human, unit: '', icon: 'hard-drive', tone: 'amber' }
] : [])

const dailyOption = computed(() => ({
  grid: { left: 44, right: 20, top: 16, bottom: 26 },
  tooltip: { trigger: 'axis' },
  xAxis: {
    type: 'category',
    data: (statistics.value?.daily || []).map((item) => item.date),
    axisLine: { lineStyle: { color: '#DCE6F2' } },
    axisTick: { show: false },
    axisLabel: { color: '#8CA4BC', fontSize: 11 }
  },
  yAxis: {
    type: 'value',
    splitLine: { lineStyle: { color: '#EDF2F8' } },
    axisLabel: { color: '#8CA4BC', fontSize: 11 }
  },
  series: [{
    type: 'bar',
    barWidth: 18,
    data: (statistics.value?.daily || []).map((item) => item.count),
    itemStyle: {
      borderRadius: [4, 4, 0, 0],
      color: {
        type: 'linear', x: 0, y: 0, x2: 0, y2: 1,
        colorStops: [{ offset: 0, color: chartC.value.primary300 }, { offset: 1, color: chartC.value.primary }]
      }
    },
    label: { show: true, position: 'top', color: '#567792', fontSize: 11 }
  }]
}))

const nodeDistOption = computed(() => ({
  tooltip: { trigger: 'item', formatter: '{b}: {c} 个 ({d}%)' },
  legend: { bottom: 0, icon: 'circle', itemWidth: 8, itemHeight: 8, textStyle: { color: '#567792', fontSize: 11.5 } },
  series: [{
    type: 'pie',
    radius: ['46%', '70%'],
    center: ['50%', '42%'],
    itemStyle: { borderColor: '#fff', borderWidth: 2 },
    label: { show: false },
    data: (statistics.value?.by_node || []).map((item) => ({ name: item.node_name, value: item.count }))
  }]
}))

// 实时刷新：收到新上传媒体事件后重新加载
realtime.connect({
  // 页面级订阅
  onMedia: (payload) => {
    if (payload.action === 'created') {
      loadMeta()
      load()
    }
  }
}, 'media')

onMounted(async () => {
  await loadMeta()
  await load()
  // 支持从其它页面跳转时直接打开预览
  const previewId = route.query.preview
  if (previewId) {
    const res = await api.media.detail(Number(previewId))
    if (res.code === 0) openPreview(res.data)
  }
})

watch(() => route.query.preview, async (value) => {
  if (!value) return
  const res = await api.media.detail(Number(value))
  if (res.code === 0) openPreview(res.data)
})
</script>

<template>
  <div>
    <!-- 统计卡 -->
    <div class="grid-4 mb-16">
      <div v-for="card in statCards" :key="card.label" class="stat" :class="`tone-${card.tone}`">
        <div class="stat-icon"><AppIcon :name="card.icon" :size="19" /></div>
        <div>
          <div class="stat-label">{{ card.label }}</div>
          <div class="stat-value">{{ card.value }}<em v-if="card.unit">{{ card.unit }}</em></div>
        </div>
      </div>
    </div>

    <div class="grid-2 mb-16">
      <div class="card">
        <div class="card-head"><div class="card-title"><i class="bar" />近 7 天上传趋势</div></div>
        <div class="card-body"><EChart :option="dailyOption" :height="196" /></div>
      </div>
      <div class="card">
        <div class="card-head"><div class="card-title"><i class="bar" />各节点媒体分布</div></div>
        <div class="card-body"><EChart :option="nodeDistOption" :height="196" /></div>
      </div>
    </div>

    <!-- 筛选 -->
    <div class="card mb-16">
      <div class="card-body tight">
        <div class="toolbar">
          <div class="search-box">
            <AppIcon name="search" :size="16" />
            <input v-model="filters.keyword" class="search-input" placeholder="搜索文件名 / 备注" @keyup.enter="search" />
          </div>
          <select v-model="filters.node_id" class="select" style="width: 200px" @change="search">
            <option value="">全部节点</option>
            <option v-for="node in nodes" :key="node.id" :value="node.id">{{ node.name }}</option>
          </select>
          <select v-model="filters.file_type" class="select" style="width: 116px" @change="search">
            <option value="">全部类型</option>
            <option value="image">图片</option>
            <option value="video">视频</option>
          </select>
          <input v-model="filters.start" class="input" type="date" style="width: 148px" @change="search" />
          <span class="muted-2">至</span>
          <input v-model="filters.end" class="input" type="date" style="width: 148px" @change="search" />
          <button class="btn" @click="search"><AppIcon name="search" :size="15" />查询</button>
          <button class="btn btn-ghost" @click="reset">重置</button>
          <div class="grow" />
          <div class="view-switch">
            <button :class="{ active: viewMode === 'grid' }" @click="viewMode = 'grid'"><AppIcon name="layers" :size="15" /></button>
            <button :class="{ active: viewMode === 'list' }" @click="viewMode = 'list'"><AppIcon name="list" :size="15" /></button>
          </div>
          <button v-if="userStore.canOperate && selected.length" class="btn btn-danger" @click="removeSelected">
            <AppIcon name="trash" :size="15" />删除选中（{{ selected.length }}）
          </button>
          <button class="btn" @click="load"><AppIcon name="refresh" :size="15" />刷新</button>
        </div>
      </div>
    </div>

    <!-- 网格视图 -->
    <div v-if="viewMode === 'grid'" class="card">
      <div class="card-head">
        <div class="card-title"><i class="bar" />数据资产库</div>
        <span class="muted small">共 {{ total }} 个文件</span>
      </div>
      <div class="card-body">
        <div v-if="loading" class="media-grid">
          <div v-for="n in 8" :key="n" class="skeleton" style="aspect-ratio: 4/3; border-radius: 10px" />
        </div>
        <EmptyState
          v-else-if="!items.length"
          icon="media"
          title="暂无媒体文件"
          description="节点抓拍的图片与录制的视频将在此统一归档，支持按节点、类型与时间筛选"
        />
        <div v-else class="media-grid">
          <div
            v-for="item in items"
            :key="item.id"
            class="media-card"
            :class="{ selected: selected.includes(item.id) }"
            @click="openPreview(item)"
          >
            <div class="media-box">
              <img v-if="item.file_type === 'image'" :src="mediaUrl(item.thumb_url || item.url)" :alt="item.file_name" loading="lazy" />
              <div v-else class="video-ph">
                <AppIcon name="play-circle" :size="30" :stroke="1.4" />
                <span class="tiny">{{ item.duration_sec ? `${item.duration_sec.toFixed(0)} 秒` : '视频' }}</span>
              </div>
              <span class="type-chip">{{ item.file_type_label }}</span>
              <span v-if="item.tags?.length" class="tag-chip">{{ item.tags[0] }}</span>
              <label v-if="userStore.canOperate" class="pick" @click.stop>
                <input type="checkbox" :checked="selected.includes(item.id)" @change="toggleSelect(item)" />
              </label>
            </div>
            <div class="media-meta">
              <div class="ellipsis small" :title="item.file_name">{{ item.file_name }}</div>
              <div class="row-between mt-6">
                <span class="tiny muted-2 ellipsis">{{ item.node_name }}</span>
                <span class="tiny muted-2 nowrap">{{ item.file_size_human }}</span>
              </div>
              <div class="tiny muted-2 mt-6">{{ fmtTime(item.captured_at, false) }}</div>
            </div>
          </div>
        </div>

        <div v-if="total > pageSize" class="pagination" style="margin: 16px -20px -18px">
          <span>共 {{ total }} 个文件 · 第 {{ page }} / {{ Math.ceil(total / pageSize) }} 页</span>
          <div class="pager">
            <button :disabled="page <= 1" @click="page--; load()">上一页</button>
            <button :disabled="page >= Math.ceil(total / pageSize)" @click="page++; load()">下一页</button>
          </div>
        </div>
      </div>
    </div>

    <!-- 列表视图 -->
    <div v-else class="card">
      <div class="card-head">
        <div class="card-title"><i class="bar" />数据资产列表</div>
        <span class="muted small">共 {{ total }} 个文件</span>
      </div>
      <div class="card-body flush">
        <div class="table-wrap" style="min-width: 1040px">
          <table class="tbl">
            <thead>
              <tr>
                <th style="width: 66px">预览</th>
                <th v-for="col in columns" :key="col.key" :style="{ width: col.width, textAlign: col.align || 'left' }">{{ col.label }}</th>
              </tr>
            </thead>
            <tbody>
              <tr v-if="!items.length"><td :colspan="columns.length + 1">
                <EmptyState icon="media" title="暂无媒体文件" />
              </td></tr>
              <tr v-for="item in items" :key="item.id">
                <td>
                  <div class="mini-thumb" @click="openPreview(item)">
                    <img v-if="item.file_type === 'image'" :src="mediaUrl(item.thumb_url || item.url)" loading="lazy" />
                    <AppIcon v-else name="play-circle" :size="18" />
                  </div>
                </td>
                <td><span class="ellipsis small" :title="item.file_name">{{ item.file_name }}</span></td>
                <td><span class="tag" :class="item.file_type === 'video' ? 'tag-purple' : 'tag-teal'">{{ item.file_type_label }}</span></td>
                <td>
                  <router-link :to="`/nodes/${item.node_id}`" class="small">{{ item.node_name }}</router-link>
                  <div class="tiny muted-2 mono">{{ item.node_uid }}</div>
                </td>
                <td class="num text-right">{{ item.file_size_human }}</td>
                <td class="num">{{ item.width && item.height ? `${item.width}×${item.height}` : '—' }}
                  <span v-if="item.duration_sec" class="muted-2"> / {{ item.duration_sec.toFixed(0) }}s</span>
                </td>
                <td class="small mono">{{ fmtTime(item.captured_at) }}</td>
                <td>
                  <div class="actions">
                    <button class="btn btn-sm" @click="openPreview(item)"><AppIcon name="eye" :size="13" />查看</button>
                    <button class="btn btn-sm" title="下载原文件" @click="download(item)">
                      <AppIcon name="download" :size="13" />
                    </button>
                    <button v-if="userStore.canOperate" class="btn btn-sm btn-danger" @click="removeOne(item)">
                      <AppIcon name="trash" :size="13" />
                    </button>
                  </div>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
        <div v-if="total > pageSize" class="pagination">
          <span>共 {{ total }} 个文件 · 第 {{ page }} / {{ Math.ceil(total / pageSize) }} 页</span>
          <div class="pager">
            <button :disabled="page <= 1" @click="page--; load()">上一页</button>
            <button :disabled="page >= Math.ceil(total / pageSize)" @click="page++; load()">下一页</button>
          </div>
        </div>
      </div>
    </div>

    <!-- 预览弹窗 -->
    <AppModal
      :model-value="!!preview"
      :title="preview?.file_name || '媒体预览'"
      size="xl"
      :hide-footer="true"
      @update:model-value="(v) => { if (!v) preview = null }"
    >
      <div v-if="preview" class="preview-wrap">
        <div class="preview-stage">
          <img v-if="preview.file_type === 'image'" :src="mediaUrl(preview.url)" :alt="preview.file_name" />
          <video v-else :src="mediaUrl(preview.url)" controls autoplay preload="metadata" />
        </div>
        <aside class="preview-side">
          <div class="info-block">
            <div class="info-title">文件信息</div>
            <div class="info-row"><span>类型</span><strong>{{ preview.file_type_label }}</strong></div>
            <div class="info-row"><span>大小</span><strong>{{ preview.file_size_human }}</strong></div>
            <div class="info-row"><span>分辨率</span><strong>{{ preview.width ? `${preview.width}×${preview.height}` : '—' }}</strong></div>
            <div v-if="preview.duration_sec" class="info-row"><span>时长</span><strong>{{ preview.duration_sec.toFixed(1) }} 秒</strong></div>
            <div class="info-row"><span>采集时间</span><strong>{{ fmtTime(preview.captured_at) }}</strong></div>
            <div class="info-row"><span>上传时间</span><strong>{{ fmtTime(preview.created_at) }}</strong></div>
            <div class="info-row"><span>来源节点</span><strong class="ellipsis">{{ preview.node_name }}</strong></div>
            <div class="info-row"><span>采集方式</span><strong>{{ preview.source === 'scheduled' ? '定时采集' : preview.source === 'manual' ? '指令触发' : preview.source }}</strong></div>
            <div class="info-row"><span>内容指纹</span><strong class="mono tiny ellipsis" :title="preview.sha256">{{ (preview.sha256 || '').slice(0, 20) }}…</strong></div>
          </div>

          <div class="info-block">
            <div class="info-title">标签与备注</div>
            <input v-model="editingTags" class="input" placeholder="标签，英文逗号分隔" />
            <textarea v-model="editingRemark" class="textarea mt-10" placeholder="备注信息" />
            <button v-if="userStore.canOperate" class="btn btn-primary btn-block mt-10" @click="saveMeta">
              <AppIcon name="check" :size="14" />保存修改
            </button>
          </div>

          <div class="row gap-8">
            <button class="btn grow" @click="download(preview)"><AppIcon name="download" :size="14" />下载原文件</button>
            <router-link class="btn grow" :to="`/nodes/${preview.node_id}`">
              <AppIcon name="node" :size="14" />查看节点
            </router-link>
          </div>
          <button v-if="userStore.canOperate" class="btn btn-danger btn-block" @click="removeOne(preview)">
            <AppIcon name="trash" :size="14" />删除该文件
          </button>
        </aside>
      </div>
    </AppModal>
  </div>
</template>

<style scoped>
.toolbar { display: flex; align-items: center; gap: 9px; flex-wrap: wrap; }
.search-box {
  display: flex; align-items: center; gap: 7px;
  height: 34px; padding: 0 11px; min-width: 220px;
  border: 1px solid var(--c-border-strong); border-radius: var(--radius-sm);
  background: var(--c-surface); color: var(--c-text-3);
}
.search-box:focus-within { border-color: var(--c-primary); box-shadow: 0 0 0 3px var(--c-primary-100); }
.search-input { flex: 1; border: none; outline: none; background: transparent; font-family: inherit; font-size: 13px; min-width: 0; }

.view-switch { display: flex; border: 1px solid var(--c-border-strong); border-radius: var(--radius-sm); overflow: hidden; }
.view-switch button {
  width: 34px; height: 32px; border: none; background: var(--c-surface);
  color: var(--c-text-2); cursor: pointer; display: flex; align-items: center; justify-content: center;
}
.view-switch button.active { background: var(--c-primary-100); color: var(--c-primary-600); }

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
.stat-value em { font-size: 12px; font-style: normal; color: var(--c-text-3); margin-left: 3px; font-weight: 500; }
.tone-primary { --tone-color: var(--c-primary); --tone-bg: var(--c-primary-100); }
.tone-teal { --tone-color: var(--c-teal); --tone-bg: var(--c-teal-100); }
.tone-purple { --tone-color: var(--c-purple); --tone-bg: var(--c-purple-100); }
.tone-amber { --tone-color: var(--c-amber); --tone-bg: var(--c-amber-100); }

.media-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(206px, 1fr)); gap: 14px; }
.media-card {
  border: 1px solid var(--c-border); border-radius: 11px; overflow: hidden;
  cursor: pointer; background: var(--c-surface); transition: all 0.16s;
}
.media-card:hover { border-color: var(--c-primary-300); box-shadow: var(--shadow); transform: translateY(-2px); }
.media-card.selected { border-color: var(--c-primary); box-shadow: 0 0 0 2px var(--c-primary-100); }
.media-box { position: relative; aspect-ratio: 4 / 3; background: var(--c-surface-3); overflow: hidden; }
.media-box img { width: 100%; height: 100%; object-fit: cover; display: block; }
.video-ph {
  width: 100%; height: 100%; display: flex; flex-direction: column; gap: 4px;
  align-items: center; justify-content: center;
  background: linear-gradient(135deg, #1A3F63, #0E2B47); color: #7FE3D0;
}
.type-chip {
  position: absolute; left: 7px; top: 7px; padding: 1px 7px; border-radius: 4px;
  background: rgba(10, 30, 50, 0.7); color: #fff; font-size: 10.5px;
}
.tag-chip {
  position: absolute; left: 7px; bottom: 7px; padding: 1px 7px; border-radius: 4px;
  background: rgba(17, 160, 143, 0.9); color: #fff; font-size: 10.5px;
}
.pick { position: absolute; right: 7px; top: 7px; }
.pick input { width: 15px; height: 15px; accent-color: var(--c-primary); cursor: pointer; }
.media-meta { padding: 9px 11px 11px; }

.mini-thumb {
  width: 46px; height: 34px; border-radius: 6px; overflow: hidden;
  background: var(--c-surface-3); display: flex; align-items: center; justify-content: center;
  color: var(--c-primary); cursor: pointer;
}
.mini-thumb img { width: 100%; height: 100%; object-fit: cover; }

.preview-wrap { display: grid; grid-template-columns: minmax(0, 1fr) 300px; gap: 18px; }
.preview-stage {
  background: #0C1F33; border-radius: 11px; overflow: hidden;
  display: flex; align-items: center; justify-content: center; min-height: 380px;
}
.preview-stage img, .preview-stage video { max-width: 100%; max-height: 66vh; display: block; }
.preview-side { display: flex; flex-direction: column; gap: 14px; }
.info-block { padding: 13px 14px; border-radius: 10px; background: var(--c-surface-2); border: 1px solid var(--c-border); }
.info-title { font-size: 12.5px; font-weight: 600; margin-bottom: 9px; color: var(--c-text-2); }
.info-row { display: flex; align-items: center; justify-content: space-between; gap: 10px; padding: 4px 0; font-size: 12.5px; }
.info-row span { color: var(--c-text-3); flex-shrink: 0; }
.info-row strong { font-weight: 500; text-align: right; min-width: 0; }

@media (max-width: 1080px) { .preview-wrap { grid-template-columns: 1fr; } }
</style>
