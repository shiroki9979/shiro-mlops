import { currentLocale, useLocaleStore } from './locale-store'
import { messagesFor } from './use-messages'

function applyDocumentLocale(): void {
  const locale = currentLocale()
  document.documentElement.lang = locale
  document.title = messagesFor(locale).app.documentTitle
}

// Applies the active locale synchronously so the first paint already carries the right lang and title,
// then keeps both in step with later switches. Returns the unsubscribe function.
export function syncDocumentLocale(): () => void {
  applyDocumentLocale()
  return useLocaleStore.subscribe(applyDocumentLocale)
}
