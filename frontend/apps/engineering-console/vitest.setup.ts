import '@testing-library/jest-dom/vitest'
import { afterAll, afterEach, beforeAll, beforeEach } from 'vitest'
import { server } from './src/mocks/server'
import { resetLocaleForTest } from './tests/support/locale-helpers'

// jsdom has no ResizeObserver, which Radix primitives observe
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
