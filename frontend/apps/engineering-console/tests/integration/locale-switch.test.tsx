import { afterEach, describe, expect, it } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { createMemoryHistory, RouterProvider } from '@tanstack/react-router'
import { syncDocumentLocale } from '@shiro-mlops/shared/i18n/document-locale'
import { LOCALE_STORAGE_KEY } from '@shiro-mlops/shared/i18n/locale-store'
import { createAppRouter } from '@/router'
import { documentTitleFor } from '@/i18n/messages'
import { en } from '@/i18n/en'
import { zhTW } from '@/i18n/zh-TW'

let stopDocumentSync: () => void = () => {}

function renderAppAt(path: string) {
  // main.tsx starts the document sync before rendering; tests mirror that entry point.
  stopDocumentSync = syncDocumentLocale(documentTitleFor)
  const router = createAppRouter(createMemoryHistory({ initialEntries: [path] }))
  return render(<RouterProvider router={router} />)
}

afterEach(() => stopDocumentSync())

describe('Engineering Console language switch', () => {
  it('offers each language under its own name in the shell, not on the settings page', async () => {
    renderAppAt('/console/settings')

    const select = await screen.findByLabelText(zhTW.localeSwitcher.label)

    expect(select).toHaveValue('zh-TW')
    expect(screen.getByRole('option', { name: '正體中文' })).toBeInTheDocument()
    expect(screen.getByRole('option', { name: 'English' })).toBeInTheDocument()
    expect(screen.getAllByRole('combobox')).toHaveLength(1)
  })

  it('switches navigation, html lang and document title together and remembers the choice', async () => {
    const user = userEvent.setup()
    renderAppAt('/console/monitoring')
    expect(await screen.findByRole('link', { name: zhTW.nav.settings })).toBeInTheDocument()
    expect(document.documentElement.lang).toBe('zh-TW')
    expect(document.title).toBe(zhTW.app.documentTitle)

    await user.selectOptions(screen.getByLabelText(zhTW.localeSwitcher.label), 'English')

    expect(await screen.findByRole('link', { name: en.nav.settings })).toBeInTheDocument()
    expect(screen.queryByRole('link', { name: zhTW.nav.settings })).not.toBeInTheDocument()
    expect(screen.getByRole('heading', { name: en.monitoring.title })).toBeInTheDocument()
    expect(screen.getByLabelText(en.localeSwitcher.label)).toHaveValue('en')
    expect(document.documentElement.lang).toBe('en')
    expect(document.title).toBe(en.app.documentTitle)
    expect(JSON.parse(localStorage.getItem(LOCALE_STORAGE_KEY) ?? '{}').state).toEqual({ preference: 'en' })
  })
})
