import { fileURLToPath, URL } from 'node:url'

import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// 仅加 dev 代理与别名，其余保持 create-vue 脚手架默认（§12.7）
export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  server: {
    port: 5173,
    proxy: {
      // 开发模式：/api 请求代理到本地后端（§12.5 端口约定）
      '/api': { target: 'http://localhost:8000', changeOrigin: true },
    },
  },
})
