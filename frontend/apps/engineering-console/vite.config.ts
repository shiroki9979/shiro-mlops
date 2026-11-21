import { resolve } from 'node:path'
import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import svgr from 'vite-plugin-svgr'
import { defineConfig } from 'vitest/config'
import { apiDevProxy } from '../../tooling/vite-dev-proxy'

// The Engineering Console shares the Forecast View's origin under this prefix (ADR-0014 §2.5).
// Vite exposes it as import.meta.env.BASE_URL, which the router and in-app links read, including in tests.
// The single source for this path: frontend/nginx.conf, frontend/Dockerfile, scripts/smoke_nginx.py
// and scripts/check_forecast_view_bundle.mjs cannot import it, so each names this constant instead.
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
    proxy: apiDevProxy,
  },
  test: {
    globals: true,
    environment: 'jsdom',
    setupFiles: ['./vitest.setup.ts'],
    // A host zone other than Asia/Taipei makes tests fail when a formatter falls back to the browser zone.
    env: { TZ: 'UTC' },
  },
})
