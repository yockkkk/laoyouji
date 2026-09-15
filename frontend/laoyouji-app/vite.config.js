import { defineConfig } from 'vite'
import uni from '@dcloudio/vite-plugin-uni'

import os from 'os'

// 后端部署在服务器上。H5 开发时由 vite 代理转发 /api，浏览器只访问 localhost，
// 既能绕开"浏览器系统代理把公网 IP:8000 拦成 request:fail"，也不再有跨域预检。
const BACKEND_TARGET = 'http://159.75.94.149:8000'

// 自动检测真实物理网卡 IP（避开 Clash 等 TUN 虚拟网卡 198.18.x.x），
// 代理向后端发包时绑定本地物理 IP，直接走网关，杜绝 Clash Tunnel 拦截重置。
function getPhysicalLocalAddress() {
  const ifaces = os.networkInterfaces()
  for (const [name, addrs] of Object.entries(ifaces)) {
    if (name.toLowerCase().includes('clash')) continue
    for (const a of addrs) {
      if (a.family === 'IPv4' && !a.internal && !a.address.startsWith('198.18.')) {
        return a.address
      }
    }
  }
  return undefined
}

const localAddress = getPhysicalLocalAddress()

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
    port: 5174, // 5173 被本机 zncp 项目的 vite 占着 ::1，localhost 会撞过去
    host: '0.0.0.0',
    proxy: {
      '/api': {
        target: BACKEND_TARGET,
        changeOrigin: true,
        secure: false,
        ws: false,
        localAddress,
      },
    },
  },
})
