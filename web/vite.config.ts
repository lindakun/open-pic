import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { fileURLToPath, URL } from 'node:url'

// 构建产物直接输出到后端的静态目录，由 FastAPI 托管
// 旧前端仍在 static/ 根下，新前端落在 static/app/，通过 MEDIA_LIB_FRONTEND 切换
export default defineConfig({
  plugins: [vue()],
  base: '/app/',
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  build: {
    outDir: '../media-library/scripts/static/app',
    emptyOutDir: true,
    // 产物名带 hash，配合后端的 immutable 缓存策略
    rollupOptions: {
      output: {
        entryFileNames: 'assets/[name].[hash].js',
        chunkFileNames: 'assets/[name].[hash].js',
        assetFileNames: 'assets/[name].[hash].[ext]',
      },
    },
  },
  server: {
    port: 5173,
    // 开发时把 API 代理到本地后端，避免跨域
    proxy: {
      '/api': 'http://127.0.0.1:18100',
      '/f': 'http://127.0.0.1:18100',
      '/t': 'http://127.0.0.1:18100',
      '/p': 'http://127.0.0.1:18100',
      '/img': 'http://127.0.0.1:18100',
    },
  },
})
