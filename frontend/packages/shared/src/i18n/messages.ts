import { type Locale, useLocale } from './locale-store'

export interface LocaleMessages<M> {
  messagesFor: (locale: Locale) => M
  useMessages: () => M
}

// Dictionaries stay in each app (ADR-0014 §2.3); only the lookup by active locale is shared.
export function createMessages<M>(dictionaries: Record<Locale, M>): LocaleMessages<M> {
  const messagesFor = (locale: Locale): M => dictionaries[locale]
  return {
    messagesFor,
    useMessages: () => messagesFor(useLocale()),
  }
}
