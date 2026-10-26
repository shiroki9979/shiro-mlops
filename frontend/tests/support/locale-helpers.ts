import { useLocaleStore } from '@/i18n/locale-store'

// jsdom reports en-US as the browser language, so every test starts in zh-TW unless it switches explicitly.
export function resetLocaleForTest() {
  useLocaleStore.setState({ preference: 'zh-TW' })
  localStorage.clear()
}
