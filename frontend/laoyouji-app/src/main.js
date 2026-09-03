import { createSSRApp } from 'vue'
import App from './App.vue'
import LyjBack from './components/LyjBack.vue'

export function createApp() {
  const app = createSSRApp(App)
  app.component('LyjBack', LyjBack) // 顶部返回箭头，各非根页直接用 <LyjBack />
  return { app }
}
