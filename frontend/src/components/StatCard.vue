<script setup>
import { computed } from 'vue'
import AppIcon from './AppIcon.vue'

const props = defineProps({
  label: { type: String, default: '' },
  value: { type: [String, Number], default: '—' },
  unit: { type: String, default: '' },
  icon: { type: String, default: 'activity' },
  tone: { type: String, default: 'primary' },   // primary | teal | green | amber | red | purple
  hint: { type: String, default: '' },
  trend: { type: [Number, null], default: null },
  loading: { type: Boolean, default: false }
})

const displayValue = computed(() => {
  if (props.loading) return ''
  if (typeof props.value === 'number') {
    return props.value.toLocaleString('zh-CN')
  }
  return props.value ?? '—'
})
</script>

<template>
  <div class="stat" :class="`tone-${tone}`">
    <div class="stat-icon">
      <AppIcon :name="icon" :size="20" />
    </div>
    <div class="stat-main">
      <div class="stat-label">{{ label }}</div>
      <div v-if="loading" class="skeleton stat-skeleton" />
      <div v-else class="stat-value">
        <span>{{ displayValue }}</span>
        <em v-if="unit">{{ unit }}</em>
      </div>
      <div v-if="hint" class="stat-hint">{{ hint }}</div>
    </div>
    <div v-if="trend !== null && trend !== undefined" class="stat-trend" :class="trend >= 0 ? 'up' : 'down'">
      <AppIcon :name="trend >= 0 ? 'arrow-up' : 'arrow-down'" :size="12" :stroke="2.2" />
      {{ Math.abs(trend) }}%
    </div>
  </div>
</template>

<style scoped>
.stat {
  position: relative;
  display: flex;
  align-items: flex-start;
  gap: 13px;
  padding: 17px 18px;
  background: var(--c-surface);
  border: 1px solid var(--c-border);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-sm);
  overflow: hidden;
  transition: box-shadow 0.18s, transform 0.18s;
}
.stat::after {
  content: '';
  position: absolute;
  inset: 0 auto 0 0;
  width: 3px;
  background: var(--tone-color, var(--c-primary));
}
.stat:hover { box-shadow: var(--shadow); transform: translateY(-1px); }
.stat-icon {
  width: 42px; height: 42px; flex-shrink: 0;
  display: flex; align-items: center; justify-content: center;
  border-radius: 11px;
  color: var(--tone-color, var(--c-primary));
  background: var(--tone-bg, var(--c-primary-100));
}
.stat-main { flex: 1; min-width: 0; }
.stat-label { font-size: 12.5px; color: var(--c-text-2); margin-bottom: 3px; }
.stat-value {
  display: flex; align-items: baseline; gap: 4px;
  font-size: 25px; font-weight: 600; line-height: 1.15;
  color: var(--c-text);
  font-variant-numeric: tabular-nums;
}
.stat-value em { font-size: 12.5px; font-weight: 500; font-style: normal; color: var(--c-text-3); }
.stat-hint { margin-top: 4px; font-size: 11.5px; color: var(--c-text-3); }
.stat-skeleton { width: 72px; height: 26px; }
.stat-trend {
  display: flex; align-items: center; gap: 2px;
  font-size: 11.5px; font-weight: 600; padding: 2px 6px; border-radius: 5px;
}
.stat-trend.up { color: #B33131; background: var(--c-red-100); }
.stat-trend.down { color: #17804F; background: var(--c-green-100); }

.tone-primary { --tone-color: var(--c-primary); --tone-bg: var(--c-primary-100); }
.tone-teal { --tone-color: var(--c-teal); --tone-bg: var(--c-teal-100); }
.tone-green { --tone-color: var(--c-green); --tone-bg: var(--c-green-100); }
.tone-amber { --tone-color: var(--c-amber); --tone-bg: var(--c-amber-100); }
.tone-red { --tone-color: var(--c-red); --tone-bg: var(--c-red-100); }
.tone-purple { --tone-color: var(--c-purple); --tone-bg: var(--c-purple-100); }
</style>
