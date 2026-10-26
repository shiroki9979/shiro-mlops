import { create } from 'zustand'
import { persist } from 'zustand/middleware'

export const SUPPORTED_LOCALES = ['zh-TW', 'en'] as const
export type Locale = (typeof SUPPORTED_LOCALES)[number]

export const DEFAULT_LOCALE: Locale = 'zh-TW'

// Each language names itself so a reader can find their own language whatever the UI language is.
export const LOCALE_NATIVE_NAMES: Record<Locale, string> = {
  'zh-TW': '正體中文',
  en: 'English',
}

export function isLocale(value: string): value is Locale {
  return (SUPPORTED_LOCALES as readonly string[]).includes(value)
}

export function detectLocale(languages: readonly string[]): Locale {
  for (const language of languages) {
    const normalized = language.toLowerCase()
    if (normalized.startsWith('zh')) return 'zh-TW'
    if (normalized.startsWith('en')) return 'en'
  }
  return DEFAULT_LOCALE
}

interface LocaleState {
  // null means the user has not chosen; the browser preference then decides on every load.
  preference: Locale | null
  setLocale: (locale: Locale) => void
}

export const useLocaleStore = create<LocaleState>()(
  persist(
    (set) => ({
      preference: null,
      setLocale: (preference) => set({ preference }),
    }),
    {
      name: 'shiro-locale',
      partialize: (state) => ({ preference: state.preference }),
    },
  ),
)

function resolveLocale(preference: Locale | null): Locale {
  return preference ?? detectLocale(navigator.languages)
}

export function currentLocale(): Locale {
  return resolveLocale(useLocaleStore.getState().preference)
}

export function useLocale(): Locale {
  return resolveLocale(useLocaleStore((state) => state.preference))
}
