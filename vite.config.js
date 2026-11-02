import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// https://vite.dev/config/
export default defineConfig({
  plugins: [vue(), {
    name: 'private-research-paths',
    configureServer(server) {
      server.middlewares.use((request, response, next) => {
        let path
        try { path = decodeURIComponent((request.url || '').split('?')[0]).replaceAll('\\', '/') }
        catch { response.statusCode = 400; response.end(); return }
        // Deny even nonexistent paths, before the SPA fallback can return index.html.
        if (/(^|\/)(backend|data|answer\.jsonl)(\/|$)/i.test(path)) {
          response.statusCode = 403
          response.end('Private research path')
          return
        }
        next()
      })
    },
  }],

  server: {
    // Research labels, private artifacts and source files must never be served by Vite.
    fs: { deny: ['.env', '.env.*', '*.{crt,pem}', '**/.git/**', '**/backend/**', '**/answer.jsonl', '**/data/**'] },
    // 允許其他裝置透過目前主機的 IP 存取
    host: '0.0.0.0',
    port: 5173,

    // 前端統一透過 /api 存取 Flask
    // 不再需要寫死主機 IP
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:5000',
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, ''),
      },
    },

    watch: {
      ignored: [
        '**/backend/preprocess_output/**',
        '**/backend/output/**',
        '**/backend/uploads/**',
        '**/data/**',
      ],
    },
  },
})
