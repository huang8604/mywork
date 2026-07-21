import { fileURLToPath, URL } from 'node:url'
import vue from '@vitejs/plugin-vue'
import { defineConfig } from 'vitest/config'

// Default backend is the native dev server on :8000. For LAN debugging via the
// myword-lan-backend Docker container (which avoids host :8000 = signtools),
// set VITE_API_TARGET=http://127.0.0.1:8001 (see dev-lan.sh).
const apiTarget = process.env.VITE_API_TARGET ?? 'http://127.0.0.1:8000'
// The backend's auth (app/core/auth.py) treats loopback as local (TRUSTED_LOCAL_WEB)
// and any TRUSTED_PROXY_CIDRS peer as a reverse proxy that MUST inject X-Forwarded-User.
// The Docker LAN path reaches the container via the docker bridge (172.16/12), i.e.
// the trusted-proxy branch, so the dev proxy has to supply that web identity itself.
const proxyUser = process.env.VITE_PROXY_USER ?? 'lan-dev'
const proxyTarget = {
  target: apiTarget,
  changeOrigin: false,
  headers: { 'X-Forwarded-User': proxyUser },
}

export default defineConfig({
  plugins: [vue()],
  resolve: { alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) } },
  server: {
    port: 5173,
    proxy: { '/api': proxyTarget, '/healthz': proxyTarget },
  },
  test: {
    environment: 'jsdom',
    setupFiles: ['./tests/unit/setup.ts'],
    include: ['./tests/unit/**/*.spec.ts'],
    css: true,
  },
})
