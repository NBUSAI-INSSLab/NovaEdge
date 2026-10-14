import { defineStore } from 'pinia'

/** 轻量全局提示（不引第三方组件库） */
export const useToastStore = defineStore('toast', {
  state: () => ({ items: [] }),
  actions: {
    push(message, type = 'info', duration = 3200) {
      const id = Date.now() + Math.random()
      this.items.push({ id, message, type })
      setTimeout(() => {
        this.items = this.items.filter((item) => item.id !== id)
      }, duration)
    },
    success(message) { this.push(message, 'success') },
    error(message) { this.push(message, 'error', 4200) },
    warning(message) { this.push(message, 'warning') },
    info(message) { this.push(message, 'info') }
  }
})
