<script setup>
import { computed, ref, watch } from 'vue'
import { api } from '@/api'
import { useToastStore } from '@/stores/toast'
import AppModal from './AppModal.vue'
import AppIcon from './AppIcon.vue'

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  nodes: { type: Array, default: () => [] }   // [{ id, name, node_uid, status }]
})
const emit = defineEmits(['update:modelValue', 'issued'])

const toast = useToastStore()
const catalog = ref([])
const selectedCommand = ref('')
const params = ref({})
const timeoutSec = ref(30)
const submitting = ref(false)

watch(() => props.modelValue, async (open) => {
  if (!open) return
  if (!catalog.value.length) {
    const res = await api.commands.catalog()
    if (res.code === 0) catalog.value = res.data
  }
  if (!selectedCommand.value && catalog.value.length) selectCommand(catalog.value[0].command)
})

const current = computed(() => catalog.value.find((item) => item.command === selectedCommand.value))
const targetsText = computed(() =>
  props.nodes.length === 1 ? `${props.nodes[0].name}（${props.nodes[0].node_uid}）` : `${props.nodes.length} 个节点`
)

function selectCommand(name) {
  selectedCommand.value = name
  const item = catalog.value.find((entry) => entry.command === name)
  params.value = { ...(item?.params || {}) }
}

function isNumber(value) {
  return typeof value === 'number'
}

async function submit() {
  if (!props.nodes.length) {
    toast.warning('请选择目标节点')
    return
  }
  submitting.value = true
  try {
    const res = await api.commands.issue({
      node_ids: props.nodes.map((node) => node.id),
      command: selectedCommand.value,
      params: params.value,
      timeout_sec: Number(timeoutSec.value) || 30
    })
    if (res.code === 0) {
      toast.success(res.message + (res.data.mqtt_pushed ? `（实时下发 ${res.data.mqtt_pushed} 条）` : ''))
      emit('update:modelValue', false)
      emit('issued', res.data)
    } else {
      toast.error(res.message)
    }
  } finally {
    submitting.value = false
  }
}
</script>

<template>
  <AppModal
    :model-value="modelValue"
    title="下发控制指令"
    confirm-text="确认下发"
    :loading="submitting"
    size="lg"
    @update:model-value="emit('update:modelValue', $event)"
    @confirm="submit"
  >
    <div class="target-box">
      <AppIcon name="target" :size="17" />
      <div class="grow">
        <div class="small">
          目标节点：<strong>{{ targetsText }}</strong>
        </div>
        <div v-if="nodes.length > 1" class="tiny muted mt-6">
          {{ nodes.map((n) => n.name).join('、') }}
        </div>
      </div>
    </div>

    <div class="mt-16">
      <div class="field-label mb-10">选择指令</div>
      <div class="cmd-grid">
        <button
          v-for="item in catalog"
          :key="item.command"
          class="cmd-card"
          :class="{ active: selectedCommand === item.command }"
          @click="selectCommand(item.command)"
        >
          <AppIcon :name="item.command === 'capture_image' ? 'camera'
            : item.command === 'start_record' ? 'video'
            : item.command === 'stop_record' ? 'stop'
            : item.command === 'set_interval' ? 'clock'
            : item.command === 'sync_config' ? 'sync'
            : item.command === 'self_test' ? 'shield' : 'power'" :size="19" />
          <div class="cmd-name">{{ item.label }}</div>
          <div class="cmd-desc">{{ item.desc }}</div>
        </button>
      </div>
    </div>

    <div v-if="current && Object.keys(params).length" class="mt-16">
      <div class="field-label mb-10">指令参数</div>
      <div class="form-grid">
        <div v-for="(value, key) in params" :key="key" class="field">
          <label class="field-label">{{ key }}</label>
          <input
            v-if="isNumber(value)"
            v-model.number="params[key]"
            class="input"
            type="number"
          />
          <input v-else v-model="params[key]" class="input" />
        </div>
      </div>
    </div>

    <div class="mt-16">
      <div class="field-label mb-10">执行超时（秒）</div>
      <input v-model.number="timeoutSec" class="input" type="number" min="5" max="1800" style="max-width: 180px" />
    </div>

    <div class="tip mt-16">
      <AppIcon name="info" :size="15" />
      <div>
        指令优先通过 MQTT 实时下发；若平台未启用 MQTT 或节点内网受限，
        节点将在下一次轮询（最长 {{ timeoutSec }} 秒）时取到指令。
        抓拍与录像类指令执行后会由节点自动上传媒体文件并回执结果。
      </div>
    </div>
  </AppModal>
</template>

<style scoped>
.target-box {
  display: flex; align-items: center; gap: 11px;
  padding: 12px 14px; border-radius: 10px;
  background: var(--c-primary-50); border: 1px solid var(--c-primary-100);
  color: var(--c-primary-600);
}
.cmd-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 10px; }
.cmd-card {
  display: flex; flex-direction: column; align-items: flex-start; gap: 4px;
  padding: 12px 13px; text-align: left;
  border: 1px solid var(--c-border); border-radius: 10px;
  background: var(--c-surface); color: var(--c-text-2);
  cursor: pointer; font-family: inherit; transition: all 0.16s;
}
.cmd-card:hover { border-color: var(--c-primary-300); background: var(--c-primary-50); }
.cmd-card.active {
  border-color: var(--c-primary); background: var(--c-primary-50);
  box-shadow: 0 0 0 3px var(--c-primary-100);
  color: var(--c-primary-600);
}
.cmd-name { font-size: 13px; font-weight: 600; color: var(--c-text); }
.cmd-desc { font-size: 11.5px; color: var(--c-text-3); line-height: 1.5; }

.tip {
  display: flex; gap: 9px; padding: 11px 13px;
  border-radius: 9px; background: var(--c-surface-2);
  border: 1px dashed var(--c-border-strong);
  font-size: 12.5px; color: var(--c-text-2); line-height: 1.65;
}
@media (max-width: 720px) { .cmd-grid { grid-template-columns: 1fr; } }
</style>
