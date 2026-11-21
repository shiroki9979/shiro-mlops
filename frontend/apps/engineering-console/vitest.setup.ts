import '@testing-library/jest-dom/vitest'
import { afterAll, afterEach, beforeAll, beforeEach } from 'vitest'
import { server } from './src/mocks/server'
import { resetLocaleForTest } from '@shiro-mlops/shared/testing/locale'

// jsdom has no ResizeObserver, which Radix primitives observe
class ResizeObserverMock {
  observe() {}
  unobserve() {}
  disconnect() {}
}
window.ResizeObserver = ResizeObserverMock
window.scrollTo = () => {}
// jsdom lacks the pointer-capture and scrolling APIs the Radix Select trigger and list call
Element.prototype.hasPointerCapture = () => false
Element.prototype.releasePointerCapture = () => {}
Element.prototype.scrollIntoView = () => {}

beforeAll(() => server.listen({ onUnhandledRequest: 'error' }))
beforeEach(() => resetLocaleForTest())
afterEach(() => server.resetHandlers())
afterAll(() => server.close())
