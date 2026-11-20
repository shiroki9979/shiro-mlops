import { resolve } from 'node:path'
import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import svgr from 'vite-plugin-svgr'
import { defineConfig } from 'vitest/config'

// The Engineering Console shares the Forecast View's origin under this prefix (ADR-0014 §2.5).
// Vite exposes it as import.meta.env.BASE_URL, which the router and in-app links read, including in tests.
// Must match the `/console/` locations in frontend/nginx.conf.
const CONSOLE_BASE_PATH = '/console/'

// https://vitejs.dev/config/
export default defineConfig({
  base: CONSOLE_BASE_PATH,
  plugins: [react(), tailwindcss(), svgr()],
  resolve: {
    alias: {
      '@': resolve(__dirname, './src'),
    },
  },
  server: {
    port: 5174,
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, ''),
      },
    },
  },
  test: {
    globals: true,
    environment: 'jsdom',
    setupFiles: ['./vitest.setup.ts'],
    // A host zone other than Asia/Taipei makes tests fail when a formatter falls back to the browser zone.
    env: { TZ: 'UTC' },
  },
})
