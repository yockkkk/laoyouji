import { defineConfig } from 'vite'
import uni from '@dcloudio/vite-plugin-uni'

export default defineConfig({
  plugins: [uni()],
  server: {
    port: 5174, // 5173 被本机 zncp 项目的 vite 占着 ::1，localhost 会撞过去
    host: '0.0.0.0',
  },
})
