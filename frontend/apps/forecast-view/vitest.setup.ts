import '@testing-library/jest-dom/vitest'
import { afterAll, afterEach, beforeAll, beforeEach } from 'vitest'
import { server } from './src/mocks/server'
import { resetLocaleForTest } from '@shiro-mlops/shared/testing/locale'

// Polyfill ResizeObserver for Recharts in JSDOM
class ResizeObserverMock {
  observe() {}
  unobserve() {}
  disconnect() {}
}
window.ResizeObserver = ResizeObserverMock
window.scrollTo = () => {}

beforeAll(() => server.listen({ onUnhandledRequest: 'error' }))
beforeEach(() => resetLocaleForTest())
afterEach(() => server.resetHandlers())
afterAll(() => server.close())
