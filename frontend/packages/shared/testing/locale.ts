import { DEFAULT_LOCALE, useLocaleStore } from '../src/i18n/locale-store'

// jsdom reports en-US as the browser language, so every test starts in the default locale unless it
// switches explicitly. Imported by each package's vitest setup; never by production sources.
export function resetLocaleForTest() {
  useLocaleStore.setState({ preference: DEFAULT_LOCALE })
  localStorage.clear()
}
