import { defineStore } from 'pinia'

const KEY = 'novaedge_theme'

/** 可选配色（顺序即选择面板展示顺序，colors 为预览色块） */
export const THEMES = [
  { key: 'blue', label: '海蓝', desc: '默认 · 沉稳专业', colors: ['#1D6FB8', '#0C3054', '#7FE3D0'] },
  { key: 'orange', label: '橙色', desc: '暖调 · 活力醒目', colors: ['#E07A18', '#2C1A0A', '#FFB861'] },
  { key: 'orangeblue', label: '橙蓝', desc: '蓝底橙调 · 品牌感', colors: ['#E8821E', '#0F3D66', '#F5A94F'] },
  { key: 'blackgray', label: '黑灰', desc: '石墨 · 极简克制', colors: ['#4A5761', '#14171B', '#B7C2CC'] },
  { key: 'green', label: '绿色', desc: '自然 · 清新护眼', colors: ['#1E9E63', '#082B20', '#6FE0AE'] }
]

/**
 * 配色主题：写入 <html data-theme="…">，由 theme.css 中的变量覆盖块生效。
 * 选择持久化到 localStorage，刷新后保持。
 */
export const useThemeStore = defineStore('theme', {
  state: () => ({
    current: localStorage.getItem(KEY) || 'blue',
    visible: false          // 配色选择面板开关
  }),
  actions: {
    /** 应用启动时调用，尽早设置主题避免闪烁 */
    init() {
      this.apply(this.current, false)
    },
    apply(key, persist = true) {
      const theme = THEMES.find((item) => item.key === key) || THEMES[0]
      this.current = theme.key
      document.documentElement.dataset.theme = theme.key
      if (persist) localStorage.setItem(KEY, theme.key)
    },
    togglePanel() {
      this.visible = !this.visible
    },
    closePanel() {
      this.visible = false
    }
  }
})
