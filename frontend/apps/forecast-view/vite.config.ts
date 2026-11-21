import { mkdirSync, writeFileSync } from 'node:fs'
import { dirname, relative, resolve } from 'node:path'
import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import type { Plugin } from 'vite'
import svgr from 'vite-plugin-svgr'
import { defineConfig } from 'vitest/config'
import { apiDevProxy } from '../../tooling/vite-api-proxy'

const FRONTEND_ROOT = resolve(__dirname, '../..')
// Read by scripts/check_forecast_view_bundle.mjs; kept out of dist so it is never deployed.
const BUNDLE_MODULES_REPORT = resolve(__dirname, 'node_modules/.cache/bundle-modules.json')

// Records every module bundled into the cloud build, so CI can prove no Engineering Console code
// or console-only dependency reaches it (ADR-0014 §4).
function bundleModulesReport(): Plugin {
  return {
    name: 'bundle-modules-report',
    apply: 'build',
    generateBundle(_options, bundle) {
      const ids = new Set<string>()
      for (const output of Object.values(bundle)) {
        if (output.type !== 'chunk') continue
        for (const id of Object.keys(output.modules)) {
          ids.add(id.startsWith('\0') ? id : relative(FRONTEND_ROOT, id))
        }
      }
      mkdirSync(dirname(BUNDLE_MODULES_REPORT), { recursive: true })
      writeFileSync(BUNDLE_MODULES_REPORT, JSON.stringify([...ids].sort(), null, 2))
    },
  }
}

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss(), svgr(), bundleModulesReport()],
  resolve: {
    alias: {
      '@': resolve(__dirname, './src'),
    },
  },
  server: {
    port: 5173,
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
