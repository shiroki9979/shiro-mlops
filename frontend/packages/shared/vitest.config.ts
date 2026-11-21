import react from '@vitejs/plugin-react'
import { defineConfig } from 'vitest/config'

export default defineConfig({
  plugins: [react()],
  test: {
    globals: true,
    environment: 'jsdom',
    setupFiles: ['./vitest.setup.ts'],
    // A host zone other than Asia/Taipei makes tests fail when a formatter falls back to the browser zone.
    env: { TZ: 'UTC' },
  },
})
