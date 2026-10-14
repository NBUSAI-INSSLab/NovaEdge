<script setup>
import { onMounted, onUnmounted, ref, watch, nextTick } from 'vue'
import * as echarts from 'echarts/core'
import { LineChart, BarChart, PieChart, GaugeChart } from 'echarts/charts'
import {
  GridComponent, TooltipComponent, LegendComponent, TitleComponent,
  DataZoomComponent, MarkLineComponent, MarkAreaComponent, ToolboxComponent
} from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'

echarts.use([
  LineChart, BarChart, PieChart, GaugeChart,
  GridComponent, TooltipComponent, LegendComponent, TitleComponent,
  DataZoomComponent, MarkLineComponent, MarkAreaComponent, ToolboxComponent,
  CanvasRenderer
])

const props = defineProps({
  option: { type: Object, required: true },
  height: { type: [String, Number], default: 280 },
  loading: { type: Boolean, default: false }
})

const el = ref(null)
let chart = null
let observer = null

function render() {
  if (!el.value) return
  if (!chart) chart = echarts.init(el.value, null, { renderer: 'canvas' })
  chart.setOption(props.option, true)
  if (props.loading) {
    // 加载色从当前主题的 CSS 变量读取，切配色时保持一致
    const style = getComputedStyle(document.documentElement)
    const cssVar = (name, fallback) => style.getPropertyValue(name).trim() || fallback
    chart.showLoading('default', {
      text: '加载中',
      color: cssVar('--c-primary', '#1D6FB8'),
      textColor: cssVar('--c-text-2', '#567792'),
      maskColor: 'rgba(255,255,255,0.72)', fontSize: 12
    })
  } else chart.hideLoading()
}

onMounted(async () => {
  await nextTick()
  render()
  observer = new ResizeObserver(() => chart && chart.resize())
  if (el.value) observer.observe(el.value)
})

onUnmounted(() => {
  if (observer) observer.disconnect()
  if (chart) { chart.dispose(); chart = null }
})

watch(() => props.option, render, { deep: true })
watch(() => props.loading, render)
</script>

<template>
  <div ref="el" class="chart" :style="{ height: typeof height === 'number' ? `${height}px` : height }" />
</template>

<style scoped>
.chart { width: 100%; }
</style>
