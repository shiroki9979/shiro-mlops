import { expect, it } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { LocaleSwitcher } from '../src/i18n/locale-switcher'
import { LOCALE_STORAGE_KEY, useLocaleStore } from '../src/i18n/locale-store'

it('offers each language under its own name and marks the active one', () => {
  render(<LocaleSwitcher label="語系" />)

  const select = screen.getByLabelText('語系')
  expect(select).toHaveValue('zh-TW')
  expect(screen.getByRole('option', { name: '正體中文' })).toHaveAttribute('lang', 'zh-TW')
  expect(screen.getByRole('option', { name: 'English' })).toHaveAttribute('lang', 'en')
})

it('saves the chosen language as an explicit preference', async () => {
  const user = userEvent.setup()
  render(<LocaleSwitcher label="語系" />)

  await user.selectOptions(screen.getByLabelText('語系'), 'English')

  expect(useLocaleStore.getState().preference).toBe('en')
  expect(screen.getByLabelText('語系')).toHaveValue('en')
  expect(JSON.parse(localStorage.getItem(LOCALE_STORAGE_KEY) ?? '{}').state).toEqual({ preference: 'en' })
})
