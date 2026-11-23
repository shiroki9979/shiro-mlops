import { describe, expect, it, vi } from 'vitest'
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { createMemoryHistory, RouterProvider } from '@tanstack/react-router'
import { http, HttpResponse } from 'msw'
import { createAppRouter } from '@/router'
import { server } from '@/mocks/server'
import { zhTW } from '@/i18n/zh-TW'
import { en } from '@/i18n/en'
import { type Locale, useLocaleStore } from '@shiro-mlops/shared/i18n/locale-store'

const m = zhTW
const results = m.explorer.results
const datasets = m.explorer.datasets

// `path` is relative to the console base path, so each case reads like the console route it opens.
function renderPath(path: string) {
  const history = createMemoryHistory({ initialEntries: [`/console${path}`] })
  return render(<RouterProvider router={createAppRouter(history)} />)
}

function typeInto(label: string, value: string) {
  fireEvent.change(screen.getByLabelText(label), { target: { value } })
}

describe('Data Explorer routes', () => {
  it('keeps the default time window when opening a detail later', async () => {
    vi.useFakeTimers({ toFake: ['Date'] })
    try {
      vi.setSystemTime(new Date('2026-09-09T12:00:00Z'))
      const user = userEvent.setup()
      renderPath('/data/power/load')
      await screen.findByText('32,100.5')

      vi.setSystemTime(new Date('2026-09-09T12:02:00Z'))
      await user.click(screen.getByText('32,100.5'))
      await screen.findByText(m.explorer.detail.title)

      expect(screen.getByLabelText(m.explorer.filters.start)).toHaveValue('2026-09-08T20:00')
      expect(screen.getByLabelText(m.explorer.filters.end)).toHaveValue('2026-09-09T20:00')
      await user.click(screen.getByText(m.common.nextPage))
      await screen.findByText('30,100')
      expect(screen.getByLabelText(m.explorer.filters.end)).toHaveValue('2026-09-09T20:00')
    } finally {
      vi.useRealTimers()
    }
  })

  it('refreshes operational status alongside the current data page', async () => {
    const user = userEvent.setup()
    renderPath('/data/power/load')
    await screen.findByText('32,100.5')
    await screen.findByText(m.common.labeled(m.status.freshnessLabel, m.status.freshness.fresh))
    server.use(http.get('*/data/status', () => HttpResponse.json({
      timezone: 'Asia/Taipei',
      datasets: [{
        id: 'hourly_load', label: 'Hourly load', href: '/data/power/load',
        availability: 'available', freshness: 'warning', completeness: 'complete',
        overall: 'warning', ingestion_age_seconds: 9000,
      }],
    })))

    // The header has its own refresh button for the health check; this one lives in the page.
    await user.click(within(screen.getByRole('main')).getByRole('button', { name: m.common.refresh }))

    expect(
      await screen.findByText(m.common.labeled(m.status.freshnessLabel, m.status.freshness.warning)),
    ).toBeInTheDocument()
    expect(screen.getByText(m.explorer.statusCard.ingestionAge('9,000'))).toBeInTheDocument()
    expect(screen.getByText('32,100.5')).toBeInTheDocument()
  })

  it('shows hourly load status and deep link on the overview', async () => {
    renderPath('/data')
    await waitFor(() => {
      expect(screen.getAllByText(m.explorer.statusCard.openDetails).length).toBeGreaterThan(0)
    })
    expect(screen.getAllByText(datasets.hourly_load.label).length).toBeGreaterThan(1)
    expect(screen.getByText(/Asia\/Taipei/)).toBeInTheDocument()
    // The status API names console routes without the base path; links must still stay inside the console.
    expect(screen.getAllByText(m.explorer.statusCard.openDetails)[0]).toHaveAttribute('href', '/console/data/power/load')
  })

  it('keeps filters in the URL, paginates, opens typed detail, and exports the current page', async () => {
    const user = userEvent.setup()
    renderPath('/data/power/load?start=2026-09-09T00:00:00%2B08:00&end=2026-09-09T20:00:00%2B08:00&subject=nationwide')

    await waitFor(() => {
      expect(screen.getByText('32,100.5')).toBeInTheDocument()
    })
    expect(screen.getAllByText(m.explorer.fields.subject).length).toBeGreaterThan(0)
    expect(screen.getByPlaceholderText('nationwide')).toHaveValue('nationwide')
    expect(screen.getAllByText('nationwide').length).toBeGreaterThan(0)
    expect(screen.getByText(results.gaps('1'))).toBeInTheDocument()
    expect(screen.getByText((text) => text.startsWith(m.explorer.filters.lastFetched('')))).toBeInTheDocument()

    await user.click(screen.getByText('32,100.5'))
    expect(screen.getByText(m.explorer.detail.title)).toBeInTheDocument()
    expect(screen.getByText(m.explorer.fields.ingested_at)).toBeInTheDocument()

    await user.click(screen.getByText(m.common.nextPage))
    await waitFor(() => {
      expect(screen.getByText('30,100')).toBeInTheDocument()
    })

    await user.click(screen.getByText(m.common.exportCsv))
    expect(screen.getByText(m.common.exportCsv)).toBeInTheDocument()
  })

  it('lists Data Explorer datasets in the sidebar when the feature is enabled', async () => {
    renderPath('/')
    await waitFor(() => {
      expect(screen.getByRole('link', { name: m.nav.dataExplorer })).toHaveAttribute('href', '/console/data')
    })
    expect(screen.getByRole('link', { name: datasets.hourly_load.label })).toHaveAttribute('href', '/console/data/power/load')
    expect(screen.getByRole('link', { name: datasets.national_supply_demand.label })).toHaveAttribute('href', '/console/data/power/supply-demand')
    expect(screen.getByRole('link', { name: datasets.regional_supply_demand.label })).toHaveAttribute('href', '/console/data/power/regional')
    expect(screen.getByRole('link', { name: datasets.unit_generation.label })).toHaveAttribute('href', '/console/data/power/units')
    expect(screen.getByRole('link', { name: datasets.cwa_observations.label })).toHaveAttribute('href', '/console/data/weather/observations')
    expect(screen.getByRole('link', { name: datasets.cwa_forecasts.label })).toHaveAttribute('href', '/console/data/weather/forecasts')
    expect(screen.getByRole('link', { name: datasets.cwa_observation_audits.label })).toHaveAttribute(
      'href',
      '/console/data/audits?type=observations',
    )
    expect(screen.getByRole('link', { name: datasets.cwa_forecast_audits.label })).toHaveAttribute(
      'href',
      '/console/data/audits?type=forecasts',
    )
    for (const group of Object.values(m.explorer.navGroups)) {
      expect(screen.getByText(group)).toBeInTheDocument()
    }
  })

  it('hides Data Explorer navigation when the feature is disabled', async () => {
    server.use(
      http.get('*/health', () =>
        HttpResponse.json({
          status: 'ok',
          version: '0.1.0',
          environment: 'test',
          model_loaded: true,
          data_explorer_enabled: false,
        }),
      ),
    )
    renderPath('/')
    await waitFor(() => {
      expect(screen.getByText(m.nav.monitoring)).toBeInTheDocument()
    })
    await waitFor(() => {
      expect(screen.queryByText(m.nav.dataExplorer)).not.toBeInTheDocument()
    })
    expect(screen.queryByRole('link', { name: datasets.hourly_load.label })).not.toBeInTheDocument()
    expect(screen.queryByRole('link', { name: datasets.cwa_observation_audits.label })).not.toBeInTheDocument()
  })

  it('hides Data Explorer navigation when health is unavailable', async () => {
    server.use(http.get('*/health', () => HttpResponse.error()))
    renderPath('/')
    await waitFor(() => {
      expect(screen.getByText(m.nav.monitoring)).toBeInTheDocument()
    })
    expect(screen.queryByRole('link', { name: m.nav.dataExplorer })).not.toBeInTheDocument()
    expect(screen.queryByRole('link', { name: datasets.hourly_load.label })).not.toBeInTheDocument()
  })

  it.each([
    [400, results.cursorRejected],
    [422, results.invalidFilters],
    [503, results.databaseUnavailable],
  ])('distinguishes HTTP %s list failures', async (status, message) => {
    server.use(
      http.get('*/data/power/load', () =>
        HttpResponse.json({ detail: 'request failed' }, { status }),
      ),
    )

    renderPath('/data/power/load')

    await waitFor(() => {
      expect(screen.getByText(message)).toBeInTheDocument()
    }, { timeout: status === 503 ? 2500 : 1000 })
  })

  it('reports a list body that breaks the schema as a failed query without retrying', async () => {
    const requests: URL[] = []
    server.use(http.get('*/data/power/load', ({ request }) => {
      requests.push(new URL(request.url))
      return HttpResponse.json({ timezone: 'Asia/Taipei', items: 'not rows' })
    }))

    renderPath('/data/power/load?cursor=old')

    expect(await screen.findByText(results.queryFailed)).toBeInTheDocument()
    expect(requests).toHaveLength(1)
    expect(screen.queryByRole('button', { name: results.backToFirstPage })).not.toBeInTheDocument()
  })

  it.each([
    ['/data/power/load', 'subject=nationwide', 'subject', 'nationwide'],
    ['/data/weather/forecasts', 'dataset_id=F-D0047-089&issued_at=2026-09-09T08%3A00%3A00%2B08%3A00', 'issued_at', '2026-09-09T08:00:00+08:00'],
    ['/data/weather/forecasts', 'dataset_id=F-D0047-089', 'dataset_id', 'F-D0047-089'],
  ])('recovers a stale cursor on %s with %s', async (path, filters, filterKey, filterValue) => {
    const requests: URL[] = []
    server.use(http.get(`*${path}`, ({ request }) => {
      const url = new URL(request.url)
      requests.push(url)
      return url.searchParams.has('cursor')
        ? HttpResponse.json({ detail: 'Incompatible cursor version' }, { status: 400 })
        : HttpResponse.json({ timezone: 'Asia/Taipei', items: [], has_more: false, next_cursor: null, missing_slots: [] })
    }))
    const user = userEvent.setup()
    const start = '2026-09-09T00:00:00+08:00'
    const end = '2026-09-09T20:00:00+08:00'
    renderPath(`${path}?start=${encodeURIComponent(start)}&end=${encodeURIComponent(end)}&${filters}&cursor=old`)

    expect(await screen.findByRole('button', { name: results.backToFirstPage })).toBeInTheDocument()
    expect(requests).toHaveLength(1)
    expect(requests[0].searchParams.get('cursor')).toBe('old')

    await user.click(screen.getByRole('button', { name: results.backToFirstPage }))
    await screen.findByText(results.empty)
    expect(requests).toHaveLength(2)
    expect(requests[1].searchParams.has('cursor')).toBe(false)
    expect(requests[1].searchParams.get('start')).toBe(start)
    expect(requests[1].searchParams.get('end')).toBe(end)
    expect(requests[1].searchParams.get(filterKey)).toBe(filterValue)
    if (path.includes('forecasts') && filterKey === 'dataset_id') {
      expect(requests[1].searchParams.has('issued_at')).toBe(false)
    }
  })

  it.each([undefined, '2026-09-09T08:00:00+08:00'])(
    'reloads a cached first page after cursor recovery with issued_at=%s', async (issuedAt) => {
      const requests: URL[] = []
      let temperature = 27.5
      server.use(http.get('*/data/weather/forecasts', ({ request }) => {
        const url = new URL(request.url)
        requests.push(url)
        if (url.searchParams.has('cursor')) {
          return HttpResponse.json({ detail: 'Incompatible cursor version' }, { status: 400 })
        }
        return HttpResponse.json({
          timezone: 'Asia/Taipei',
          items: [{ geocode: '63000000', temperature_c: temperature }],
          has_more: true, next_cursor: 'old', missing_slots: [],
        })
      }))
      const filters = new URLSearchParams({
        start: '2026-09-09T00:00:00+08:00',
        end: '2026-09-09T20:00:00+08:00',
        dataset_id: 'F-D0047-089',
        geocode: '63000000',
      })
      if (issuedAt) {
        filters.set('issued_at', issuedAt)
        filters.set('source_updated_at', '2026-09-09T08:30:00+08:00')
      }
      const user = userEvent.setup()
      renderPath(`/data/weather/forecasts?${filters}`)
      await screen.findByText('27.5')
      await user.click(screen.getByRole('button', { name: m.common.nextPage }))
      await screen.findByRole('button', { name: results.backToFirstPage })
      expect(requests).toHaveLength(2)

      temperature = 31.5
      await user.click(screen.getByRole('button', { name: results.backToFirstPage }))

      expect(await screen.findByText('31.5')).toBeInTheDocument()
      expect(screen.queryByText('27.5')).not.toBeInTheDocument()
      expect(requests).toHaveLength(3)
      expect(Object.fromEntries(requests[2].searchParams)).toEqual({ ...Object.fromEntries(filters), limit: '200' })
    },
  )

  it.each([
    {
      change: 'the subject filter',
      path: '/data/power/load',
      apiPath: '/data/power/load',
      markerField: 'subject',
      edit: async () => typeInto(m.explorer.fields.subject, 'north'),
      sent: { subject: 'north' },
    },
    {
      change: 'the start time',
      path: '/data/power/load',
      apiPath: '/data/power/load',
      markerField: 'subject',
      edit: async () => typeInto(m.explorer.filters.start, '2026-09-09T01:00'),
      sent: { start: '2026-09-09T01:00:00+08:00' },
    },
    {
      change: 'the forecast audit status filter',
      path: '/data/audits?type=forecasts',
      apiPath: '/data/audits/cwa-forecasts',
      markerField: 'dataset_id',
      edit: async (user: ReturnType<typeof userEvent.setup>) => {
        await user.click(screen.getByRole('combobox', { name: m.explorer.fields.status }))
        await user.click(await screen.findByRole('option', { name: m.status.completeness.complete }))
      },
      sent: { status: 'complete' },
    },
  ])('returns to the first page after changing $change on a later page', async (scenario) => {
    const requests: URL[] = []
    server.use(http.get(`*${scenario.apiPath}`, ({ request }) => {
      const url = new URL(request.url)
      requests.push(url)
      const isLaterPage = url.searchParams.has('cursor')
      return HttpResponse.json({
        timezone: 'Asia/Taipei',
        items: [{ [scenario.markerField]: isLaterPage ? 'second-page-row' : 'first-page-row' }],
        has_more: !isLaterPage,
        next_cursor: isLaterPage ? null : 'page-2',
        missing_slots: [],
      })
    }))
    const queryWindow = { start: '2026-09-09T00:00:00+08:00', end: '2026-09-09T20:00:00+08:00' }
    const separator = scenario.path.includes('?') ? '&' : '?'
    const user = userEvent.setup()
    renderPath(`${scenario.path}${separator}${new URLSearchParams(queryWindow)}`)
    await screen.findByText('first-page-row')
    await user.click(screen.getByRole('button', { name: m.common.nextPage }))
    await screen.findByText('second-page-row')

    await scenario.edit(user)

    expect(await screen.findByText('first-page-row')).toBeInTheDocument()
    expect(Object.fromEntries(requests.at(-1)!.searchParams)).toEqual({ ...queryWindow, ...scenario.sent, limit: '200' })
  })

  it('closes the open detail when switching audit type from the sidebar', async () => {
    server.use(http.get('*/data/audits/cwa-observations', () => HttpResponse.json({
      timezone: 'Asia/Taipei',
      items: [{ status: 'observation-audit-row' }],
      has_more: false, next_cursor: null, missing_slots: [],
    })))
    const user = userEvent.setup()
    renderPath('/data/audits?type=observations')
    await user.click(await screen.findByText('observation-audit-row'))
    expect(screen.getByText(m.explorer.detail.title)).toBeInTheDocument()

    await user.click(screen.getByRole('link', { name: datasets.cwa_forecast_audits.label }))

    expect(await screen.findByRole('heading', { name: datasets.cwa_forecast_audits.label })).toBeInTheDocument()
    expect(screen.queryByText(m.explorer.detail.title)).not.toBeInTheDocument()
    expect(screen.queryAllByText('observation-audit-row')).toHaveLength(0)
  })

  it.each([400, 422, 503])('does not offer cursor recovery for an unrelated %s error', async (status) => {
    server.use(http.get('*/data/power/load', () => HttpResponse.json({ detail: 'failed' }, { status })))
    renderPath(`/data/power/load?${status === 400 ? '' : 'cursor=old'}`)

    await screen.findByText(status === 400
      ? results.cursorRejected
      : status === 422
        ? results.invalidFilters
        : results.databaseUnavailable, {}, { timeout: status === 503 ? 2500 : 1000 })
    expect(screen.queryByRole('button', { name: results.backToFirstPage })).not.toBeInTheDocument()
  })
})

describe('Monitoring Data Source Status', () => {
  it('uses the shared status contract and deep-links into Data Explorer', async () => {
    renderPath('/monitoring')
    await waitFor(() => {
      expect(screen.getByText(m.monitoring.sources.title)).toBeInTheDocument()
      expect(screen.getAllByText(m.monitoring.sources.openExplorer).length).toBeGreaterThan(0)
    })
    const regionalLink = screen.getAllByText(m.monitoring.sources.openExplorer).find((node) =>
      node.getAttribute('href')?.includes('completeness=incomplete'),
    )
    expect(regionalLink).toHaveAttribute('href', '/console/data/power/regional?completeness=incomplete')
    expect(screen.queryByText(/Feast Feature Store/)).not.toBeInTheDocument()
    expect(screen.queryByText(/Feature Store Snapshot/)).not.toBeInTheDocument()
  })

  it('hides explorer links when Data Explorer is disabled', async () => {
    server.use(
      http.get('*/health', () =>
        HttpResponse.json({
          status: 'ok',
          version: '0.1.0',
          environment: 'test',
          model_loaded: true,
          data_explorer_enabled: false,
        }),
      ),
    )
    renderPath('/monitoring')
    await waitFor(() => {
      expect(screen.getAllByText(m.monitoring.sources.explorerDisabled).length).toBeGreaterThan(0)
    })
    expect(screen.queryByText(m.monitoring.sources.openExplorer)).not.toBeInTheDocument()
  })
})

describe('CWA observation explorer', () => {
  it('shows latest audit fetch time and missing identifiers', async () => {
    renderPath('/data/weather/observations')
    await waitFor(() => {
      expect(screen.getByText(m.explorer.datasetStatus.latestAudit(m.status.completeness.incomplete, '2026/09/09 20:02:00'))).toBeInTheDocument()
    })
    expect(screen.getAllByText(/466920/).length).toBeGreaterThan(0)
    expect(screen.getByText(m.explorer.datasetStatus.auditHistory)).toHaveAttribute(
      'href',
      '/console/data/audits?type=observations',
    )
  })
})

// jsdom's Blob has no text(); FileReader is the available reader.
function readBlobText(blob: Blob): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => resolve(String(reader.result))
    reader.onerror = () => reject(reader.error)
    reader.readAsText(blob)
  })
}

function switchLocale(locale: Locale) {
  act(() => useLocaleStore.getState().setLocale(locale))
}

// Taipei wall-clock text for the mocked 2026-09-09T20:00:00+08:00 row; the suite runs with TZ=UTC.
// getByText collapses the thin space CLDR puts between the zh-TW date and time.
const LOAD_ROW_TIME = { 'zh-TW': '2026/09/09 20:00:00', en: '09/09/2026, 20:00:00' }

describe('Data Explorer language switch', () => {
  it('relabels table headers, cells, detail fields and status text without refetching', async () => {
    const user = userEvent.setup()
    renderPath('/data/power/load')
    await screen.findByText('32,100.5')
    await user.click(screen.getByText('32,100.5'))

    expect(screen.getByRole('columnheader', { name: zhTW.explorer.fields.load_mw })).toBeInTheDocument()
    expect(within(screen.getByRole('table')).getByText(LOAD_ROW_TIME['zh-TW'])).toBeInTheDocument()
    expect(screen.getByText(zhTW.explorer.fields.ingested_at)).toBeInTheDocument()
    expect(
      screen.getByText(zhTW.common.labeled(zhTW.status.freshnessLabel, zhTW.status.freshness.fresh)),
    ).toBeInTheDocument()

    switchLocale('en')

    expect(screen.getByRole('columnheader', { name: en.explorer.fields.load_mw })).toBeInTheDocument()
    expect(screen.queryByRole('columnheader', { name: zhTW.explorer.fields.load_mw })).not.toBeInTheDocument()
    expect(within(screen.getByRole('table')).getByText(LOAD_ROW_TIME.en)).toBeInTheDocument()
    expect(screen.getByText(en.explorer.fields.ingested_at)).toBeInTheDocument()
    expect(screen.getByText(en.common.labeled(en.status.freshnessLabel, en.status.freshness.fresh))).toBeInTheDocument()
    expect(screen.getByText(en.status.overall.warning)).toBeInTheDocument()
    expect(screen.getByRole('link', { name: en.explorer.datasets.hourly_load.label })).toBeInTheDocument()
  })

  it('relabels the cursor recovery button', async () => {
    server.use(http.get('*/data/power/load', () =>
      HttpResponse.json({ detail: 'Incompatible cursor version' }, { status: 400 })))
    renderPath('/data/power/load?cursor=old')
    expect(await screen.findByRole('button', { name: zhTW.explorer.results.backToFirstPage })).toBeInTheDocument()

    switchLocale('en')

    expect(screen.getByRole('button', { name: en.explorer.results.backToFirstPage })).toBeInTheDocument()
    expect(screen.getByText(en.explorer.results.cursorRejected)).toBeInTheDocument()
  })

  it('sends the same request parameters and exports the same CSV in every language', async () => {
    const requests: string[] = []
    server.use(http.get('*/data/power/load', ({ request }) => {
      requests.push(new URL(request.url).search)
      return HttpResponse.json({
        timezone: 'Asia/Taipei',
        items: [{ datetime: '2026-09-09T20:00:00+08:00', subject: 'nationwide', load_mw: 32100.5 }],
        has_more: false, next_cursor: null, missing_slots: [],
      })
    }))
    const exported: Blob[] = []
    Object.assign(URL, {
      createObjectURL: (blob: Blob) => {
        exported.push(blob)
        return 'blob:explorer-csv'
      },
      revokeObjectURL: () => {},
    })
    const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {})
    const path = '/data/power/load?start=2026-09-09T00%3A00%3A00%2B08%3A00&end=2026-09-09T20%3A00%3A00%2B08%3A00&subject=nationwide'

    try {
      for (const [locale, messages] of [['zh-TW', zhTW], ['en', en]] as const) {
        switchLocale(locale)
        const user = userEvent.setup()
        const view = renderPath(path)
        await screen.findByText('32,100.5')
        await user.click(screen.getByRole('button', { name: messages.common.exportCsv }))
        view.unmount()
      }
    } finally {
      click.mockRestore()
      Reflect.deleteProperty(URL, 'createObjectURL')
      Reflect.deleteProperty(URL, 'revokeObjectURL')
    }

    expect(requests).toEqual([
      '?start=2026-09-09T00%3A00%3A00%2B08%3A00&end=2026-09-09T20%3A00%3A00%2B08%3A00&subject=nationwide&limit=200',
      '?start=2026-09-09T00%3A00%3A00%2B08%3A00&end=2026-09-09T20%3A00%3A00%2B08%3A00&subject=nationwide&limit=200',
    ])
    const csv = await Promise.all(exported.map(readBlobText))
    expect(csv).toEqual([
      '"datetime","subject","load_mw"\r\n"2026-09-09T20:00:00+08:00","nationwide","32100.5"',
      '"datetime","subject","load_mw"\r\n"2026-09-09T20:00:00+08:00","nationwide","32100.5"',
    ])
  })
})

describe('Data Explorer table', () => {
  it('asks the API for its largest page of 200 rows', async () => {
    const requests: URL[] = []
    server.use(http.get('*/data/power/regional', ({ request }) => {
      requests.push(new URL(request.url))
      return HttpResponse.json({ timezone: 'Asia/Taipei', items: [], has_more: false, next_cursor: null, missing_slots: [] })
    }))
    renderPath('/data/power/regional')

    await screen.findByText(results.empty)

    expect(requests.at(-1)!.searchParams.get('limit')).toBe('200')
  })

  it('separates rows that fall on different Taipei days without making the separator selectable', async () => {
    server.use(http.get('*/data/power/regional', () => HttpResponse.json({
      timezone: 'Asia/Taipei',
      items: [
        { observed_at: '2026-11-21T00:00:00+08:00', region: 'north', load_mw: 9419, slot_complete: true },
        { observed_at: '2026-11-20T23:50:00+08:00', region: 'south', load_mw: 8288, slot_complete: true },
      ],
      has_more: false, next_cursor: null, missing_slots: [],
    })))
    const user = userEvent.setup()
    renderPath('/data/power/regional')
    const table = await screen.findByRole('table')

    const rowNames = within(table).getAllByRole('row').map((row) => row.textContent)
    const separator = within(table).getByRole('row', { name: '2026/11/20' })
    const separatorIndex = rowNames.indexOf(separator.textContent)
    expect(rowNames[separatorIndex - 1]).toContain('north')
    expect(rowNames[separatorIndex + 1]).toContain('south')

    await user.click(separator)
    expect(screen.queryByText(m.explorer.detail.title)).not.toBeInTheDocument()
  })

  it.each([
    ['/data/audits?type=forecasts', '*/data/audits/cwa-forecasts', { issued_at: '2026-11-21T05:00:00+08:00', status: 'incomplete' }, m.status.completeness.incomplete],
    ['/data/power/regional', '*/data/power/regional', { observed_at: '2026-11-21T21:00:00+08:00', slot_complete: false }, m.common.no],
  ])('reads the status badge on %s as translated text', async (path, apiPath, row, label) => {
    server.use(http.get(apiPath, () => HttpResponse.json({
      timezone: 'Asia/Taipei', items: [row], has_more: false, next_cursor: null, missing_slots: [],
    })))
    renderPath(path)

    const table = await screen.findByRole('table')

    expect(within(table).getByRole('cell', { name: label })).toBeInTheDocument()
  })
})
