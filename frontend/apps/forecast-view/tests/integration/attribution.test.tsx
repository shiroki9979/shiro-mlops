import { beforeEach, describe, expect, it } from 'vitest'
import { render, screen, within } from '@testing-library/react'
import { createMemoryHistory, RouterProvider } from '@tanstack/react-router'
import { http, HttpResponse } from 'msw'
import { useLocaleStore, type Locale } from '@shiro-mlops/shared/i18n/locale-store'
import { createAppRouter } from '@/router'
import { server } from '@/mocks/server'
import { en } from '@/i18n/en'
import { zhTW } from '@/i18n/zh-TW'

// The Open Government Data License v1.0 (政府資料開放授權條款-第1版) that the Taipower and CWA datasets use.
const LICENSE_URL = 'https://data.gov.tw/license'
const DICTIONARIES = { 'zh-TW': zhTW, en } as const

function renderAppAt(path: string, locale: Locale) {
  useLocaleStore.setState({ preference: locale })
  const router = createAppRouter(createMemoryHistory({ initialEntries: [path] }))
  render(<RouterProvider router={router} />)
  return DICTIONARIES[locale].attribution
}

// /history reads the published track record; serving it keeps every request in these tests handled.
beforeEach(() => {
  server.use(
    http.get('/published/forecast_track_record.json', () =>
      HttpResponse.json({ cutoff: '2026-11-20T10:00:00+08:00', accumulated_days: 0, metrics: null }),
    ),
  )
})

describe('Forecast View data source attribution', () => {
  it.each([
    ['/', 'zh-TW'],
    ['/history', 'zh-TW'],
    ['/', 'en'],
    ['/history', 'en'],
  ] as const)('credits the data providers and links the license at the foot of %s in %s', async (path, locale) => {
    const text = renderAppAt(path, locale)

    const footer = await screen.findByRole('contentinfo')
    expect(within(footer).getByText(text.providers)).toBeInTheDocument()
    expect(within(footer).getByText(text.statement)).toBeInTheDocument()
    const license = within(footer).getByRole('link', { name: text.licenseLink })
    expect(license).toHaveAttribute('href', LICENSE_URL)
    expect(license).toHaveAttribute('rel', 'noopener noreferrer')
  })

  it('names both providers and quotes the license statement in zh-TW', () => {
    expect(zhTW.attribution.providers).toBe('台灣電力股份有限公司、交通部中央氣象署')
    expect(zhTW.attribution.statement).toBe(
      '此開放資料依政府資料開放授權條款 (Open Government Data License) 進行公眾釋出，使用者於遵守本條款各項規定之前提下，得利用之。',
    )
  })
})
