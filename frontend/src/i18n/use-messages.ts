import { en } from './en'
import { type Locale, useLocale } from './locale-store'
import { type Messages, zhTW } from './zh-TW'

const MESSAGES: Record<Locale, Messages> = {
  'zh-TW': zhTW,
  en,
}

export function messagesFor(locale: Locale): Messages {
  return MESSAGES[locale]
}

export function useMessages(): Messages {
  return messagesFor(useLocale())
}

export type { Messages }
