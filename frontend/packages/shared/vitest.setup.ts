import '@testing-library/jest-dom/vitest'
import { beforeEach } from 'vitest'
import { useLocaleStore } from './src/i18n/locale-store'

// jsdom reports en-US as the browser language, so every test starts in zh-TW unless it switches explicitly.
beforeEach(() => {
  useLocaleStore.setState({ preference: 'zh-TW' })
  localStorage.clear()
})
