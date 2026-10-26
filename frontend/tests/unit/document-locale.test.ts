import { afterEach, expect, it, vi } from 'vitest'
import { syncDocumentLocale } from '@/i18n/document-locale'
import { useLocaleStore } from '@/i18n/locale-store'
import { en } from '@/i18n/en'
import { zhTW } from '@/i18n/zh-TW'

let stopSync: () => void = () => {}

afterEach(() => {
  stopSync()
  vi.restoreAllMocks()
  document.documentElement.lang = ''
  document.title = ''
})

it('sets html lang and title before anything renders, then follows locale switches', () => {
  stopSync = syncDocumentLocale()

  expect(document.documentElement.lang).toBe('zh-TW')
  expect(document.title).toBe(zhTW.app.documentTitle)

  useLocaleStore.getState().setLocale('en')

  expect(document.documentElement.lang).toBe('en')
  expect(document.title).toBe(en.app.documentTitle)
})

it('stops following the locale once unsubscribed', () => {
  syncDocumentLocale()()

  useLocaleStore.getState().setLocale('en')

  expect(document.documentElement.lang).toBe('zh-TW')
})

it('applies the detected browser language before first render when no choice is saved', () => {
  vi.spyOn(window.navigator, 'languages', 'get').mockReturnValue(['en-US'])
  useLocaleStore.setState({ preference: null })

  // The same call main.tsx makes ahead of ReactDOM.createRoot().render().
  stopSync = syncDocumentLocale()

  expect(document.documentElement.lang).toBe('en')
  expect(document.title).toBe(en.app.documentTitle)
})
