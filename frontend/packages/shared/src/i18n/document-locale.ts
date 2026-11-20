import { currentLocale, type Locale, useLocaleStore } from './locale-store'

// Applies the active locale synchronously so the first paint already carries the right lang and title,
// then keeps both in step with later switches. Each app passes its own title. Returns the unsubscribe function.
export function syncDocumentLocale(titleFor: (locale: Locale) => string): () => void {
  const apply = () => {
    const locale = currentLocale()
    document.documentElement.lang = locale
    document.title = titleFor(locale)
  }
  apply()
  return useLocaleStore.subscribe(apply)
}
