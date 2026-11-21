import { createMessages } from '@shiro-mlops/shared/i18n/messages'
import type { Locale } from '@shiro-mlops/shared/i18n/locale-store'
import { en } from './en'
import { type Messages, zhTW } from './zh-TW'

export const { messagesFor, useMessages } = createMessages<Messages>({ 'zh-TW': zhTW, en })

export const documentTitleFor = (locale: Locale): string => messagesFor(locale).app.documentTitle

export type { Messages }
