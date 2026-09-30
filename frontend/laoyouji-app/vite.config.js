import { defineConfig } from 'vite'
import uni from '@dcloudio/vite-plugin-uni'

// 本地开发默认直通本地后端 127.0.0.1:8000；亦可通过环境变量指向云端
const BACKEND_TARGET = process.env.VITE_BACKEND_TARGET || 'http://127.0.0.1:8000'

export default defineConfig({
  plugins: [uni()],
  css: {
    preprocessorOptions: {
      scss: {
        api: 'modern-compiler',
        silenceDeprecations: ['legacy-js-api', 'import'],
      },
    },
  },
  server: {
    port: 5174, // 5173 被本机 zncp 项目的 vite 占着 ::1，故使用 5174
    host: '0.0.0.0',
    proxy: {
      '/api': {
        target: BACKEND_TARGET,
        changeOrigin: true,
        secure: false,
        ws: false,
      },
    },
  },
})
