import { computed } from 'vue'
import { useThemeStore } from '@/stores/theme'

/**
 * 图表配色：从当前主题的 CSS 变量实时读取。
 *
 * 用法（视图内）：
 *   const chartC = useChartColors()
 *   const option = computed(() => ({ ..., lineStyle: { color: chartC.value.primary } }))
 *
 * computed 依赖 theme.current —— 切换配色时视图的 option 会重新求值，
 * EChart 组件的深度 watch 随之重绘，图表颜色即时跟随主题。
 */
export function useChartColors() {
  const theme = useThemeStore()
  return computed(() => {
    void theme.current                       // 建立响应式依赖
    const style = getComputedStyle(document.documentElement)
    const v = (name, fallback = '') => style.getPropertyValue(name).trim() || fallback
    return {
      primary: v('--c-primary', '#1D6FB8'),
      primary300: v('--c-primary-300', '#7CB4E4'),
      primary600: v('--c-primary-600', '#165A99'),
      primary700: v('--c-primary-700', '#10497C'),
      accent: v('--c-accent', '#7FE3D0'),
      text: v('--c-text', '#14283D'),
      text2: v('--c-text-2', '#567792'),
      text3: v('--c-text-3', '#8CA4BC'),
      border: v('--c-border', '#DCE6F2'),
      borderSoft: v('--c-border-soft', '#EDF2F8')
    }
  })
}

/** #RRGGBB → rgba(...)，用于面积图渐变等需要透明度的场景 */
export function hexToRgba(hex, alpha) {
  const raw = String(hex || '').replace('#', '')
  if (raw.length !== 6) return `rgba(29, 111, 184, ${alpha})`
  const r = parseInt(raw.slice(0, 2), 16)
  const g = parseInt(raw.slice(2, 4), 16)
  const b = parseInt(raw.slice(4, 6), 16)
  return `rgba(${r}, ${g}, ${b}, ${alpha})`
}
