import { afterEach, expect, it, vi } from 'vitest'
import { syncDocumentLocale } from '../src/i18n/document-locale'
import { type Locale, useLocaleStore } from '../src/i18n/locale-store'

// Each app passes its own titles; these stand in for an app dictionary.
const TITLES: Record<Locale, string> = {
  'zh-TW': '預報檢視',
  en: 'Forecast View',
}
const titleFor = (locale: Locale) => TITLES[locale]

let stopSync: () => void = () => {}

afterEach(() => {
  stopSync()
  vi.restoreAllMocks()
  document.documentElement.lang = ''
  document.title = ''
})

it('sets html lang and title before anything renders, then follows locale switches', () => {
  stopSync = syncDocumentLocale(titleFor)

  expect(document.documentElement.lang).toBe('zh-TW')
  expect(document.title).toBe('預報檢視')

  useLocaleStore.getState().setLocale('en')

  expect(document.documentElement.lang).toBe('en')
  expect(document.title).toBe('Forecast View')
})

it('stops following the locale once unsubscribed', () => {
  syncDocumentLocale(titleFor)()

  useLocaleStore.getState().setLocale('en')

  expect(document.documentElement.lang).toBe('zh-TW')
})

it('applies the detected browser language before first render when no choice is saved', () => {
  vi.spyOn(window.navigator, 'languages', 'get').mockReturnValue(['en-US'])
  useLocaleStore.setState({ preference: null })

  // The same call each app's main.tsx makes ahead of ReactDOM.createRoot().render().
  stopSync = syncDocumentLocale(titleFor)

  expect(document.documentElement.lang).toBe('en')
  expect(document.title).toBe('Forecast View')
})
