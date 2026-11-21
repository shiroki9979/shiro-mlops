import { expect, it } from 'vitest'
import { act, render, screen } from '@testing-library/react'
import { createMessages } from '../src/i18n/messages'
import { useLocaleStore } from '../src/i18n/locale-store'

// Each app owns its dictionaries; the factory only picks the one for the active locale.
const dictionaries = {
  'zh-TW': { greeting: '你好' },
  en: { greeting: 'Hello' },
}

it('looks up the dictionary for a given locale', () => {
  const { messagesFor } = createMessages(dictionaries)

  expect(messagesFor('zh-TW').greeting).toBe('你好')
  expect(messagesFor('en').greeting).toBe('Hello')
})

it('returns the dictionary of the active locale and follows switches', () => {
  const { useMessages } = createMessages(dictionaries)
  function Greeting() {
    return <p>{useMessages().greeting}</p>
  }
  render(<Greeting />)

  expect(screen.getByText('你好')).toBeInTheDocument()

  act(() => useLocaleStore.getState().setLocale('en'))

  expect(screen.getByText('Hello')).toBeInTheDocument()
})
