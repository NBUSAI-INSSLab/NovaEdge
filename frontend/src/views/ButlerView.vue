<template>
  <div class="butler-page">
    <!-- ============ 左栏：智能会话 ============ -->
    <section class="chat-panel card">
      <header class="chat-head">
        <div class="row">
          <span class="chat-avatar"><AppIcon name="butler" :size="20" /></span>
          <div>
            <div class="chat-title">智能管家</div>
            <div class="chat-sub">
              <span class="engine-badge" :class="llmEnabled ? 'is-llm' : 'is-builtin'">
                {{ llmEnabled ? '大模型驱动' : '内置规则引擎' }}
              </span>
              可查数据 · 配系统 · 出报告
            </div>
          </div>
        </div>
        <div class="row gap-8">
          <button v-if="userStore.canOperate" class="icon-btn" title="大模型设置" @click="openConfig">
            <AppIcon name="settings" :size="16" />
          </button>
          <button class="icon-btn" title="新会话" @click="newSession">
            <AppIcon name="plus" :size="16" />
          </button>
        </div>
      </header>

      <div ref="chatBox" class="chat-body">
        <div v-if="messages.length === 0" class="chat-welcome">
          <span class="welcome-icon"><AppIcon name="butler" :size="42" /></span>
          <h3>你好，我是 NovaEdge 智能管家</h3>
          <p>我可以帮你查询平台数据、执行配置操作、生成分析报告。试试下面这些问题：</p>
          <div class="quick-grid">
            <button v-for="q in QUICK_PROMPTS" :key="q" class="quick-btn" @click="send(q)">{{ q }}</button>
          </div>
        </div>

        <template v-for="(m, index) in messages" :key="index">
          <div class="msg" :class="m.role === 'user' ? 'msg-user' : 'msg-ai'">
            <span class="msg-avatar" v-if="m.role !== 'user'"><AppIcon name="butler" :size="15" /></span>
            <div class="bubble" :class="m.role === 'user' ? 'bubble-user' : 'bubble-ai'">
              <div v-if="m.role === 'user'" class="bubble-text">{{ m.content }}</div>
              <div v-else class="bubble-md" v-html="renderMarkdown(m.content)"></div>
              <div v-if="m.trace && m.trace.length" class="tool-trace">
                <button class="trace-toggle" @click="m._openTrace = !m._openTrace">
                  <AppIcon name="terminal" :size="12" />
                  工具执行（{{ m.trace.length }} 步）
                  <AppIcon :name="m._openTrace ? 'chevron-up' : 'chevron-down'" :size="12" />
                </button>
                <div v-if="m._openTrace" class="trace-list">
                  <div v-for="(t, ti) in m.trace" :key="ti" class="trace-item">
                    <code class="trace-tool">{{ t.tool }}</code>
                    <code class="trace-json">{{ compact(t.args) }}</code>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </template>

        <div v-if="thinking" class="msg msg-ai">
          <span class="msg-avatar"><AppIcon name="butler" :size="15" /></span>
          <div class="bubble bubble-ai bubble-thinking"><span></span><span></span><span></span></div>
        </div>
      </div>

      <footer class="chat-input">
        <div class="quick-row">
          <button v-for="q in QUICK_CHIPS" :key="q" class="chip" @click="send(q)">{{ q }}</button>
        </div>
        <div class="input-row">
          <input
            v-model="draft"
            class="input"
            placeholder="输入问题，回车发送…（如：最近24小时温度情况）"
            :disabled="thinking"
            @keydown.enter="send()"
          />
          <button class="btn btn-primary send-btn" :disabled="thinking || !draft.trim()" @click="send()">
            <AppIcon name="send" :size="15" /> 发送
          </button>
        </div>
      </footer>
    </section>

    <!-- ============ 右栏：分析报告 ============ -->
    <aside class="report-panel">
      <div class="card report-head-card">
        <div class="report-head">
          <div>
            <div class="chat-title">分析报告</div>
            <div class="chat-sub">一键生成平台运行分析报告</div>
          </div>
          <button v-if="userStore.canOperate" class="btn btn-primary btn-sm" :disabled="generating" @click="generate()">
            <AppIcon name="refresh" :size="14" /> {{ generating ? '生成中…' : '生成报告' }}
          </button>
        </div>
        <div class="report-types">
          <label class="radio"><input v-model="reportHours" type="radio" :value="24" /> 最近 24 小时</label>
          <label class="radio"><input v-model="reportHours" type="radio" :value="72" /> 最近 3 天</label>
          <label class="radio"><input v-model="reportHours" type="radio" :value="168" /> 最近 7 天</label>
        </div>
      </div>

      <div class="report-list">
        <EmptyState v-if="!reports.length && !loadingReports" icon="document"
                    title="暂无报告" description="点击「生成报告」，智能管家将汇总平台数据输出分析报告" />
        <button v-for="r in reports" :key="r.id" class="report-item card" @click="viewReport(r)">
          <div class="report-item-top">
            <span class="report-name">{{ r.title }}</span>
            <StatusTag :label="r.engine === 'llm' ? '大模型' : '内置引擎'"
                       :type="r.engine === 'llm' ? 'primary' : 'default'" />
          </div>
          <div class="report-meta">
            <span><AppIcon name="node" :size="12" /> {{ r.node_count }} 节点</span>
            <span><AppIcon name="alert" :size="12" /> {{ r.alert_count }} 告警</span>
            <span><AppIcon name="monitor" :size="12" /> {{ fmtNumber(r.telemetry_count) }} 数据点</span>
          </div>
          <div class="report-summary">{{ r.summary }}</div>
          <div class="report-time">{{ fmtTime(r.created_at, false) }}</div>
        </button>
      </div>
    </aside>

    <!-- 报告查看弹窗 -->
    <AppModal v-model="reportModal" :title="currentReport?.title || '报告'" width="860px">
      <div class="report-doc" v-html="reportHtml"></div>
      <template #footer>
        <button class="btn" @click="downloadReport"><AppIcon name="download" :size="14" /> 下载 Markdown</button>
        <button v-if="userStore.canOperate" class="btn btn-danger"
                @click="deleteReport(currentReport)"><AppIcon name="trash" :size="14" /> 删除</button>
        <button class="btn btn-primary" @click="reportModal = false">关闭</button>
      </template>
    </AppModal>

    <!-- 大模型配置弹窗 -->
    <AppModal v-model="configModal" title="智能管家 · 大模型配置" width="560px" :loading="savingConfig"
              confirm-text="保存配置" @confirm="saveConfig">
      <div class="config-form">
        <label class="switch-row">
          <input v-model="cfg.enabled" type="checkbox" />
          <span>启用大模型（关闭后使用内置规则引擎）</span>
        </label>
        <div class="field">
          <div class="field-label">API 地址（OpenAI 兼容，不含 /chat/completions）</div>
          <input v-model="cfg.base_url" class="input" placeholder="https://api.deepseek.com/v1" />
        </div>
        <div class="field">
          <div class="field-label">API Key {{ cfg.api_key_set ? '（已保存，留空表示不修改）' : '' }}</div>
          <input v-model="cfg.api_key" class="input" type="password" placeholder="sk-…" />
        </div>
        <div class="field-row">
          <div class="field">
            <div class="field-label">模型名称</div>
            <input v-model="cfg.model" class="input" placeholder="deepseek-chat / qwen-plus / llama3…" />
          </div>
          <div class="field" style="width: 120px">
            <div class="field-label">温度</div>
            <input v-model.number="cfg.temperature" class="input" type="number" step="0.1" min="0" max="2" />
          </div>
        </div>
        <div class="config-tip">
          兼容 OpenAI 接口规范的大模型服务均可接入：DeepSeek、通义千问、Kimi、智谱 GLM、
          本地 Ollama（地址如 <code>http://127.0.0.1:11434/v1</code>）等。
          密钥保存在平台数据库，不会下发到浏览器。
        </div>
      </div>
      <template #footer-prepend>
        <button class="btn" :disabled="testing" @click="testConfig">
          <AppIcon name="play" :size="14" /> {{ testing ? '测试中…' : '测试连接' }}
        </button>
      </template>
    </AppModal>
  </div>
</template>

<script setup>
import { nextTick, onMounted, ref } from 'vue'
import { api, fmtNumber, fmtTime } from '@/api'
import { useUserStore } from '@/stores/user'
import { useToastStore } from '@/stores/toast'
import AppIcon from '@/components/AppIcon.vue'
import AppModal from '@/components/AppModal.vue'
import StatusTag from '@/components/StatusTag.vue'
import EmptyState from '@/components/EmptyState.vue'
import { renderMarkdown } from '@/utils/markdown'

const userStore = useUserStore()
const toast = useToastStore()

const QUICK_PROMPTS = [
  '现在有几个节点在线？',
  '最近24小时告警情况',
  '数据资产里图片视频有多少',
  '最近24小时温度统计'
]
const QUICK_CHIPS = ['系统运行状况', '1号节点情况', '把温度告警阈值调到33', '查看告警规则']

const messages = ref([])
const draft = ref('')
const thinking = ref(false)
const chatBox = ref(null)
const sessionId = ref(`s_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 8)}`)
const llmEnabled = ref(false)

const reports = ref([])
const loadingReports = ref(false)
const generating = ref(false)
const reportHours = ref(24)
const reportModal = ref(false)
const currentReport = ref(null)
const reportHtml = ref('')

const configModal = ref(false)
const cfg = ref({ enabled: false, base_url: '', api_key: '', model: '', temperature: 0.4, api_key_set: false })
const savingConfig = ref(false)
const testing = ref(false)

function compact(obj) {
  try { return JSON.stringify(obj) } catch { return '{}' }
}
function scrollToBottom() {
  nextTick(() => { if (chatBox.value) chatBox.value.scrollTop = chatBox.value.scrollHeight })
}

async function send(preset) {
  const text = (preset || draft.value).trim()
  if (!text || thinking.value) return
  draft.value = ''
  messages.value.push({ role: 'user', content: text })
  thinking.value = true
  scrollToBottom()
  try {
    const res = await api.butler.chat({ session_id: sessionId.value, message: text })
    const data = res.data || {}
    messages.value.push({
      role: 'assistant', content: data.reply || '（空回复）',
      trace: data.trace || [], engine: data.engine, _openTrace: false
    })
  } catch (e) {
    messages.value.push({ role: 'assistant', content: `❌ 请求失败：${e?.message || '网络异常'}`, trace: [] })
  } finally {
    thinking.value = false
    scrollToBottom()
  }
}

function newSession() {
  sessionId.value = `s_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 8)}`
  messages.value = []
}

async function loadTools() {
  try {
    const res = await api.butler.tools()
    llmEnabled.value = !!res.data?.llm_enabled
  } catch { /* 忽略 */ }
}

// ---------- 报告 ----------
async function loadReports() {
  loadingReports.value = true
  try {
    const res = await api.butler.reports({ page: 1, page_size: 30 })
    reports.value = res.data?.items || []
  } finally {
    loadingReports.value = false
  }
}

async function generate() {
  generating.value = true
  try {
    const res = await api.butler.generateReport({ report_type: 'on_demand', hours: reportHours.value })
    toast.success('报告生成完成')
    await loadReports()
    viewReportByData(res.data)
  } catch (e) {
    toast.error(e?.message || '报告生成失败')
  } finally {
    generating.value = false
  }
}

function viewReportByData(data) {
  currentReport.value = data
  reportHtml.value = renderMarkdown(data.content_md)
  reportModal.value = true
}

async function viewReport(r) {
  const res = await api.butler.report(r.id)
  viewReportByData(res.data)
}

function downloadReport() {
  if (!currentReport.value) return
  window.open(api.butler.downloadUrl(currentReport.value.id), '_blank')
}

async function deleteReport(r) {
  if (!window.confirm(`确定删除报告「${r.title}」？此操作不可恢复。`)) return
  try {
    await api.butler.removeReport(r.id)
    toast.success('报告已删除')
    reportModal.value = false
    await loadReports()
  } catch (e) {
    toast.error(e?.message || '删除失败')
  }
}

// ---------- 大模型配置 ----------
async function openConfig() {
  const res = await api.butler.config()
  cfg.value = { ...cfg.value, ...res.data, api_key: '' }
  configModal.value = true
}

async function saveConfig() {
  if (cfg.value.enabled && (!cfg.value.base_url || !cfg.value.model)) {
    toast.warning('启用前请填写 API 地址与模型名称')
    return
  }
  savingConfig.value = true
  try {
    await api.butler.saveConfig({
      enabled: cfg.value.enabled,
      base_url: cfg.value.base_url,
      api_key: cfg.value.api_key,
      model: cfg.value.model,
      temperature: cfg.value.temperature
    })
    toast.success('配置已保存')
    configModal.value = false
    await loadTools()
  } catch (e) {
    toast.error(e?.message || '保存失败')
  } finally {
    savingConfig.value = false
  }
}

async function testConfig() {
  testing.value = true
  try {
    // 先临时保存再测试，保证测的是当前表单值
    if (cfg.value.base_url && cfg.value.model) {
      await api.butler.saveConfig({
        enabled: cfg.value.enabled, base_url: cfg.value.base_url,
        api_key: cfg.value.api_key, model: cfg.value.model,
        temperature: cfg.value.temperature
      })
      cfg.value.api_key = ''
    }
    const res = await api.butler.testConfig()
    if (res.data?.ok) toast.success(`连接成功：${res.data.reply}`)
    else toast.error(res.data?.error || '连接失败')
  } catch (e) {
    toast.error(e?.message || '测试失败')
  } finally {
    testing.value = false
  }
}

onMounted(() => {
  loadTools()
  loadReports()
})
</script>

<style scoped>
.butler-page {
  display: flex;
  gap: 16px;
  height: calc(100vh - var(--header-h) - 28px);
  min-height: 520px;
}

/* ---------- 会话面板 ---------- */
.chat-panel { flex: 1; min-width: 0; display: flex; flex-direction: column; padding: 0; overflow: hidden; }
.chat-head {
  display: flex; align-items: center; justify-content: space-between;
  padding: 14px 18px; border-bottom: 1px solid var(--c-border-soft);
}
.chat-avatar {
  width: 38px; height: 38px; border-radius: 10px; display: flex; align-items: center; justify-content: center;
  background: var(--c-primary-100); color: var(--c-primary);
}
.chat-title { font-size: 15px; font-weight: 700; color: var(--c-text); }
.chat-sub { font-size: 12px; color: var(--c-text-3); display: flex; align-items: center; gap: 6px; margin-top: 2px; }
.engine-badge { padding: 1px 8px; border-radius: 999px; font-size: 11px; font-weight: 600; }
.engine-badge.is-llm { background: var(--c-green-100); color: var(--c-green); }
.engine-badge.is-builtin { background: var(--c-amber-100); color: var(--c-amber); }

.chat-body { flex: 1; overflow-y: auto; padding: 18px; }
.chat-welcome { text-align: center; padding: 40px 20px 20px; color: var(--c-text-2); }
.welcome-icon {
  display: inline-flex; width: 72px; height: 72px; border-radius: 20px; align-items: center; justify-content: center;
  background: var(--c-primary-100); color: var(--c-primary); margin-bottom: 14px;
}
.chat-welcome h3 { margin: 0 0 6px; color: var(--c-text); font-size: 17px; }
.chat-welcome p { margin: 0 0 18px; font-size: 13px; }
.quick-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 260px)); gap: 10px; justify-content: center; }
.quick-btn {
  padding: 10px 14px; border: 1px solid var(--c-border); border-radius: 10px; background: var(--c-surface-2);
  color: var(--c-text-2); font-size: 13px; font-family: inherit; cursor: pointer; text-align: left;
}
.quick-btn:hover { border-color: var(--c-primary-300); color: var(--c-primary); background: var(--c-primary-50); }

.msg { display: flex; margin-bottom: 14px; gap: 8px; }
.msg-user { justify-content: flex-end; }
.msg-avatar {
  flex: none; width: 28px; height: 28px; border-radius: 8px; margin-top: 2px;
  display: flex; align-items: center; justify-content: center;
  background: var(--c-primary-100); color: var(--c-primary);
}
.bubble { max-width: 76%; padding: 10px 14px; border-radius: 12px; font-size: 13.5px; line-height: 1.65; }
.bubble-user { background: var(--c-primary); color: #fff; border-bottom-right-radius: 4px; }
.bubble-ai {
  background: var(--c-surface-3); color: var(--c-text); border-bottom-left-radius: 4px;
  border: 1px solid var(--c-border-soft);
}
.bubble-thinking { display: flex; gap: 5px; align-items: center; padding: 14px 16px; }
.bubble-thinking span {
  width: 7px; height: 7px; border-radius: 50%; background: var(--c-text-3);
  animation: blink 1.2s infinite ease-in-out;
}
.bubble-thinking span:nth-child(2) { animation-delay: 0.2s; }
.bubble-thinking span:nth-child(3) { animation-delay: 0.4s; }
@keyframes blink { 0%, 80%, 100% { opacity: 0.25; } 40% { opacity: 1; } }

/* markdown 气泡 */
.bubble-md :deep(p) { margin: 0 0 6px; }
.bubble-md :deep(p:last-child) { margin-bottom: 0; }
.bubble-md :deep(code) {
  background: var(--c-primary-50); color: var(--c-primary-600);
  padding: 1px 5px; border-radius: 4px; font-family: var(--font-mono); font-size: 12px;
}
.bubble-md :deep(strong) { color: var(--c-primary-600); }

.tool-trace { margin-top: 8px; }
.trace-toggle {
  display: inline-flex; align-items: center; gap: 4px; padding: 2px 8px;
  border: none; border-radius: 6px; background: var(--c-primary-50); color: var(--c-primary);
  font-size: 11.5px; font-family: inherit; cursor: pointer;
}
.trace-list { margin-top: 6px; display: flex; flex-direction: column; gap: 4px; }
.trace-item { display: flex; gap: 8px; align-items: baseline; }
.trace-tool {
  flex: none; background: var(--c-primary); color: #fff; padding: 1px 7px; border-radius: 4px;
  font-family: var(--font-mono); font-size: 11px;
}
.trace-json {
  font-family: var(--font-mono); font-size: 11px; color: var(--c-text-3);
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap; max-width: 380px;
}

.chat-input { border-top: 1px solid var(--c-border-soft); padding: 10px 16px 14px; }
.quick-row { display: flex; gap: 8px; margin-bottom: 10px; flex-wrap: wrap; }
.chip {
  padding: 4px 12px; border-radius: 999px; border: 1px solid var(--c-border);
  background: var(--c-surface); color: var(--c-text-2); font-size: 12px; font-family: inherit; cursor: pointer;
}
.chip:hover { border-color: var(--c-primary-300); color: var(--c-primary); }
.input-row { display: flex; gap: 10px; }
.input-row .input { flex: 1; }
.send-btn { flex: none; }

/* ---------- 报告面板 ---------- */
.report-panel { width: 380px; flex: none; display: flex; flex-direction: column; gap: 12px; min-height: 0; }
.report-head-card { padding: 14px 16px; }
.report-head { display: flex; align-items: center; justify-content: space-between; gap: 10px; }
.report-types { display: flex; gap: 14px; margin-top: 12px; }
.radio { display: flex; align-items: center; gap: 5px; font-size: 12.5px; color: var(--c-text-2); cursor: pointer; }
.report-list { flex: 1; overflow-y: auto; display: flex; flex-direction: column; gap: 10px; padding-bottom: 4px; }
.report-item { text-align: left; padding: 13px 15px; cursor: pointer; font-family: inherit; border: 1px solid var(--c-border); }
.report-item:hover { border-color: var(--c-primary-300); box-shadow: var(--shadow); }
.report-item-top { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
.report-name { font-size: 13.5px; font-weight: 600; color: var(--c-text); }
.report-meta { display: flex; gap: 14px; margin-top: 6px; font-size: 12px; color: var(--c-text-3); }
.report-meta span { display: inline-flex; align-items: center; gap: 4px; }
.report-summary {
  margin-top: 8px; font-size: 12px; color: var(--c-text-2); line-height: 1.5;
  display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden;
}
.report-time { margin-top: 6px; font-size: 11.5px; color: var(--c-text-3); }

/* 报告文档 */
.report-doc { max-height: 66vh; overflow-y: auto; padding: 4px 6px; }
.report-doc :deep(h1) { font-size: 20px; margin: 6px 0 12px; color: var(--c-text); }
.report-doc :deep(h2) { font-size: 16px; margin: 18px 0 8px; color: var(--c-primary-600); border-left: 3px solid var(--c-primary); padding-left: 8px; }
.report-doc :deep(h3) { font-size: 14px; margin: 14px 0 6px; color: var(--c-text); }
.report-doc :deep(p) { margin: 6px 0; font-size: 13.5px; line-height: 1.75; color: var(--c-text); }
.report-doc :deep(table) { width: 100%; border-collapse: collapse; margin: 10px 0; font-size: 13px; }
.report-doc :deep(th) {
  background: var(--c-primary-50); color: var(--c-primary-600); text-align: left;
  padding: 7px 10px; border: 1px solid var(--c-border); white-space: nowrap;
}
.report-doc :deep(td) { padding: 6px 10px; border: 1px solid var(--c-border); color: var(--c-text-2); }
.report-doc :deep(blockquote) {
  margin: 8px 0; padding: 8px 14px; border-left: 3px solid var(--c-primary-300);
  background: var(--c-primary-50); color: var(--c-text-2); border-radius: 0 8px 8px 0; font-size: 13px;
}
.report-doc :deep(hr) { border: none; border-top: 1px dashed var(--c-border); margin: 14px 0; }
.report-doc :deep(code) {
  background: var(--c-surface-3); padding: 1px 5px; border-radius: 4px;
  font-family: var(--font-mono); font-size: 12px;
}
.report-doc :deep(ul), .report-doc :deep(ol) { margin: 6px 0; padding-left: 22px; }
.report-doc :deep(li) { margin: 4px 0; font-size: 13.5px; line-height: 1.7; color: var(--c-text); }

/* 配置表单 */
.config-form { display: flex; flex-direction: column; gap: 12px; }
.switch-row { display: flex; align-items: center; gap: 8px; font-size: 13.5px; color: var(--c-text); cursor: pointer; }
.field-row { display: flex; gap: 12px; }
.field-row .field { flex: 1; }
.config-tip {
  font-size: 12px; color: var(--c-text-3); line-height: 1.6;
  background: var(--c-surface-2); border: 1px dashed var(--c-border); border-radius: 8px; padding: 10px 12px;
}
</style>
