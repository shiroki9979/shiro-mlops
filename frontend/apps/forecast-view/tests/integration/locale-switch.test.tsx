import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { createMemoryHistory, RouterProvider } from '@tanstack/react-router'
import { http, HttpResponse } from 'msw'
import { syncDocumentLocale } from '@shiro-mlops/shared/i18n/document-locale'
import { LOCALE_STORAGE_KEY } from '@shiro-mlops/shared/i18n/locale-store'
import { createAppRouter } from '@/router'
import { server } from '@/mocks/server'
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

// /history reads the published track record; serving it keeps every request in these tests handled.
beforeEach(() => {
  server.use(
    http.get('/published/forecast_track_record.json', () =>
      HttpResponse.json({ cutoff: '2026-11-20T10:00:00+08:00', accumulated_days: 0, metrics: null }),
    ),
  )
})

afterEach(() => stopDocumentSync())

describe('Forecast View language switch', () => {
  it.each(['/', '/history'])('offers each language under its own name in the shell of %s', async (path) => {
    renderAppAt(path)

    const select = await screen.findByLabelText(zhTW.localeSwitcher.label)

    expect(select).toHaveValue('zh-TW')
    expect(screen.getByRole('option', { name: '正體中文' })).toBeInTheDocument()
    expect(screen.getByRole('option', { name: 'English' })).toBeInTheDocument()
  })

  it('switches navigation, html lang and document title together and remembers the choice', async () => {
    const user = userEvent.setup()
    renderAppAt('/history')
    expect(await screen.findByRole('link', { name: zhTW.nav.history })).toBeInTheDocument()
    expect(document.documentElement.lang).toBe('zh-TW')
    expect(document.title).toBe(zhTW.app.documentTitle)

    await user.selectOptions(screen.getByLabelText(zhTW.localeSwitcher.label), 'English')

    expect(await screen.findByRole('link', { name: en.nav.history })).toBeInTheDocument()
    expect(screen.queryByRole('link', { name: zhTW.nav.history })).not.toBeInTheDocument()
    expect(screen.getByRole('heading', { name: en.history.title })).toBeInTheDocument()
    expect(screen.getByLabelText(en.localeSwitcher.label)).toHaveValue('en')
    expect(document.documentElement.lang).toBe('en')
    expect(document.title).toBe(en.app.documentTitle)
    expect(JSON.parse(localStorage.getItem(LOCALE_STORAGE_KEY) ?? '{}').state).toEqual({ preference: 'en' })
  })

  it('links only to Forecast View pages and the data license', async () => {
    renderAppAt('/')

    await screen.findByLabelText(zhTW.localeSwitcher.label)
    const hrefs = screen.getAllByRole('link').map((link) => link.getAttribute('href'))

    expect(hrefs).toEqual(['/', '/history', 'https://data.gov.tw/license'])
  })
})
