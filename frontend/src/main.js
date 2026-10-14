import { createApp } from 'vue'
import { createPinia } from 'pinia'
import App from './App.vue'
import router from './router'
import { useThemeStore } from './stores/theme'
import './styles/theme.css'

const app = createApp(App)
app.use(createPinia())

// 尽早应用已保存的配色主题，避免首帧闪烁
useThemeStore().init()

app.use(router)
app.mount('#app')
