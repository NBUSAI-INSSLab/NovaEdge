<script setup>
import { computed } from 'vue'
import AppIcon from './AppIcon.vue'

const props = defineProps({
  columns: { type: Array, required: true },   // [{ key, label, width, align, className }]
  rows: { type: Array, default: () => [] },
  loading: { type: Boolean, default: false },
  total: { type: Number, default: 0 },
  page: { type: Number, default: 1 },
  pageSize: { type: Number, default: 20 },
  rowKey: { type: String, default: 'id' },
  selectable: { type: Boolean, default: false },
  selected: { type: Array, default: () => [] },
  emptyText: { type: String, default: '暂无数据' },
  minWidth: { type: String, default: '880px' }
})

const emit = defineEmits(['update:page', 'update:selected', 'row-click'])

const pages = computed(() => Math.max(Math.ceil(props.total / props.pageSize), 1))

const pageList = computed(() => {
  const list = []
  const last = pages.value
  const current = props.page
  const push = (value) => { if (!list.includes(value) && value >= 1 && value <= last) list.push(value) }
  push(1)
  for (let i = current - 1; i <= current + 1; i += 1) push(i)
  push(last)
  const result = []
  list.sort((a, b) => a - b).forEach((value, index) => {
    if (index > 0 && value - list[index - 1] > 1) result.push('...')
    result.push(value)
  })
  return result
})

function goto(target) {
  if (target === '...' || target === props.page) return
  const next = Math.min(Math.max(target, 1), pages.value)
  emit('update:page', next)
}

const allChecked = computed(() =>
  props.rows.length > 0 && props.rows.every((row) => props.selected.includes(row[props.rowKey]))
)

function toggleAll(event) {
  if (event.target.checked) {
    const merged = new Set(props.selected)
    props.rows.forEach((row) => merged.add(row[props.rowKey]))
    emit('update:selected', [...merged])
  } else {
    const keys = new Set(props.rows.map((row) => row[props.rowKey]))
    emit('update:selected', props.selected.filter((key) => !keys.has(key)))
  }
}

function toggleRow(row) {
  const key = row[props.rowKey]
  const next = props.selected.includes(key)
    ? props.selected.filter((item) => item !== key)
    : [...props.selected, key]
  emit('update:selected', next)
}
</script>

<template>
  <div class="dt">
    <div class="table-wrap" :style="{ minWidth }">
      <table class="tbl">
        <thead>
          <tr>
            <th v-if="selectable" style="width: 42px">
              <input type="checkbox" :checked="allChecked" @change="toggleAll" />
            </th>
            <th
              v-for="col in columns"
              :key="col.key"
              :style="{ width: col.width, textAlign: col.align || 'left' }"
            >{{ col.label }}</th>
          </tr>
        </thead>
        <tbody>
          <tr v-if="loading" v-for="n in Math.min(pageSize, 6)" :key="`sk-${n}`">
            <td v-if="selectable"><div class="skeleton" style="width: 16px; height: 16px" /></td>
            <td v-for="col in columns" :key="col.key">
              <div class="skeleton" :style="{ width: `${50 + (n * 7) % 40}%`, height: '14px' }" />
            </td>
          </tr>
          <tr v-else-if="!rows.length">
            <td :colspan="columns.length + (selectable ? 1 : 0)">
              <div class="empty">
                <AppIcon name="inbox" :size="26" :stroke="1.4" />
                <span>{{ emptyText }}</span>
              </div>
            </td>
          </tr>
          <tr
            v-else
            v-for="row in rows"
            :key="row[rowKey]"
            @click="emit('row-click', row)"
          >
            <td v-if="selectable" @click.stop>
              <input
                type="checkbox"
                :checked="selected.includes(row[rowKey])"
                @change="toggleRow(row)"
              />
            </td>
            <td
              v-for="col in columns"
              :key="col.key"
              :style="{ textAlign: col.align || 'left' }"
              :class="col.className"
            >
              <slot :name="`cell-${col.key}`" :row="row" :value="row[col.key]">
                {{ row[col.key] ?? '—' }}
              </slot>
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <div v-if="total > 0" class="pagination">
      <span>共 {{ total }} 条 · 第 {{ page }} / {{ pages }} 页</span>
      <div class="pager">
        <button :disabled="page <= 1" @click="goto(page - 1)">
          <AppIcon name="chevron-left" :size="14" />
        </button>
        <button
          v-for="(item, index) in pageList"
          :key="`${item}-${index}`"
          :class="{ active: item === page }"
          :disabled="item === '...'"
          @click="goto(item)"
        >{{ item }}</button>
        <button :disabled="page >= pages" @click="goto(page + 1)">
          <AppIcon name="chevron-right" :size="14" />
        </button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.dt { width: 100%; }
.dt input[type='checkbox'] { width: 15px; height: 15px; accent-color: var(--c-primary); cursor: pointer; }
</style>
