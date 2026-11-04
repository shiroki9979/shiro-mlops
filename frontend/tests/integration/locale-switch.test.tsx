import { afterEach, describe, expect, it } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { createMemoryHistory, createRouter, RouterProvider } from '@tanstack/react-router'
import { routeTree } from '../../src/routeTree'
import { syncDocumentLocale } from '@/i18n/document-locale'
import { en } from '@/i18n/en'
import { zhTW } from '@/i18n/zh-TW'

let stopDocumentSync: () => void = () => {}

function renderAppAt(path: string) {
  // main.tsx starts the document sync before rendering; tests mirror that entry point.
  stopDocumentSync = syncDocumentLocale()
  const history = createMemoryHistory({ initialEntries: [path] })
  const router = createRouter({ routeTree, history })
  return render(<RouterProvider router={router} />)
}

afterEach(() => stopDocumentSync())

describe('Interface language switch', () => {
  it('offers each language under its own name in the settings page', async () => {
    renderAppAt('/settings')

    const select = await screen.findByLabelText(zhTW.settings.language.label)

    expect(select).toHaveValue('zh-TW')
    expect(screen.getByRole('option', { name: '正體中文' })).toBeInTheDocument()
    expect(screen.getByRole('option', { name: 'English' })).toBeInTheDocument()
  })

  it('switches navigation, html lang and document title together and remembers the choice', async () => {
    const user = userEvent.setup()
    renderAppAt('/settings')
    expect(await screen.findByRole('link', { name: zhTW.nav.history })).toBeInTheDocument()
    expect(document.documentElement.lang).toBe('zh-TW')
    expect(document.title).toBe(zhTW.app.documentTitle)

    await user.selectOptions(screen.getByLabelText(zhTW.settings.language.label), 'English')

    expect(await screen.findByRole('link', { name: en.nav.history })).toBeInTheDocument()
    expect(screen.queryByRole('link', { name: zhTW.nav.history })).not.toBeInTheDocument()
    expect(screen.getByLabelText(en.settings.language.label)).toHaveValue('en')
    expect(document.documentElement.lang).toBe('en')
    expect(document.title).toBe(en.app.documentTitle)
    expect(JSON.parse(localStorage.getItem('shiro-locale') ?? '{}').state).toEqual({ preference: 'en' })
  })
})
