import { afterEach, describe, expect, it, vi } from 'vitest'

const STORAGE_KEY = 'shiro-locale'

function stubBrowserLanguages(languages: string[]) {
  vi.spyOn(window.navigator, 'languages', 'get').mockReturnValue(languages)
}

async function loadFreshLocaleModule() {
  vi.resetModules()
  return import('@/i18n/locale-store')
}

afterEach(() => {
  vi.restoreAllMocks()
  localStorage.clear()
})

describe('detectLocale', () => {
  it.each([
    [['fr-FR', 'en-GB', 'zh-TW'], 'en'],
    [['ja-JP', 'zh-HK', 'en-US'], 'zh-TW'],
    [['zh-CN'], 'zh-TW'],
    [['EN'], 'en'],
  ])('picks the first supported language from %j', async (languages, expected) => {
    const { detectLocale } = await loadFreshLocaleModule()

    expect(detectLocale(languages)).toBe(expected)
  })

  it('falls back to zh-TW when no browser language is supported', async () => {
    const { detectLocale } = await loadFreshLocaleModule()

    expect(detectLocale(['fr-FR', 'ja'])).toBe('zh-TW')
    expect(detectLocale([])).toBe('zh-TW')
  })
})

describe('isLocale', () => {
  it('accepts only supported locale codes', async () => {
    const { isLocale } = await loadFreshLocaleModule()

    expect(isLocale('zh-TW')).toBe(true)
    expect(isLocale('en')).toBe(true)
    expect(isLocale('en-US')).toBe(false)
    expect(isLocale('fr')).toBe(false)
  })
})

describe('useLocaleStore persistence', () => {
  it('uses the detected browser language without saving it', async () => {
    stubBrowserLanguages(['en-US', 'zh-TW'])

    const { currentLocale } = await loadFreshLocaleModule()

    expect(currentLocale()).toBe('en')
    expect(localStorage.getItem(STORAGE_KEY)).toBeNull()
  })

  it('keeps an explicit choice across reloads ahead of the browser preference', async () => {
    stubBrowserLanguages(['en-US'])
    const firstLoad = await loadFreshLocaleModule()

    firstLoad.useLocaleStore.getState().setLocale('zh-TW')
    const reloaded = await loadFreshLocaleModule()

    expect(reloaded.currentLocale()).toBe('zh-TW')
  })
})
