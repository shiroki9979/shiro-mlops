import { describe, expect, it, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { createMemoryHistory, createRouter, RouterProvider } from '@tanstack/react-router'
import { routeTree } from '../../src/routeTree'
import { http, HttpResponse } from 'msw'
import { server } from '../../src/mocks/server'

function renderPath(path: string) {
  const history = createMemoryHistory({ initialEntries: [path] })
  const router = createRouter({ routeTree, history })
  return render(<RouterProvider router={router} />)
}

describe('Data Explorer routes', () => {
  it('keeps the default time window when opening a detail later', async () => {
    vi.useFakeTimers({ toFake: ['Date'] })
    try {
      vi.setSystemTime(new Date('2026-09-09T12:00:00Z'))
      const user = userEvent.setup()
      renderPath('/data/power/load')
      await screen.findByText('32100.5')

      vi.setSystemTime(new Date('2026-09-09T12:02:00Z'))
      await user.click(screen.getByText('32100.5'))
      await screen.findByText('Typed detail')

      expect(screen.getByLabelText('開始時間')).toHaveValue('2026-09-08T20:00')
      expect(screen.getByLabelText('結束時間')).toHaveValue('2026-09-09T20:00')
      await user.click(screen.getByText('下一頁'))
      await screen.findByText('30100')
      expect(screen.getByLabelText('結束時間')).toHaveValue('2026-09-09T20:00')
    } finally {
      vi.useRealTimers()
    }
  })

  it('refreshes operational status alongside the current data page', async () => {
    const user = userEvent.setup()
    renderPath('/data/power/load')
    await screen.findByText('32100.5')
    await screen.findByText('freshness: fresh')
    server.use(http.get('*/data/status', () => HttpResponse.json({
      timezone: 'Asia/Taipei',
      datasets: [{
        id: 'hourly_load', label: 'Hourly load', href: '/data/power/load',
        availability: 'available', freshness: 'warning', completeness: 'complete',
        overall: 'warning', ingestion_age_seconds: 9000,
      }],
    })))

    await user.click(screen.getByText('Refresh'))

    expect(await screen.findByText('freshness: warning')).toBeInTheDocument()
    expect(screen.getByText('Ingestion age：9000 秒')).toBeInTheDocument()
    expect(screen.getByText('32100.5')).toBeInTheDocument()
  })

  it('shows hourly load status and deep link on the overview', async () => {
    renderPath('/data')
    await waitFor(() => {
      expect(screen.getAllByText('開啟明細').length).toBeGreaterThan(0)
    })
    expect(screen.getAllByText('逐時用電負載').length).toBeGreaterThan(1)
    expect(screen.getByText(/Asia\/Taipei/)).toBeInTheDocument()
  })

  it('keeps filters in the URL, paginates, opens typed detail, and exports the current page', async () => {
    const user = userEvent.setup()
    renderPath('/data/power/load?start=2026-09-09T00:00:00%2B08:00&end=2026-09-09T20:00:00%2B08:00&location=Taipei')

    await waitFor(() => {
      expect(screen.getByText('32100.5')).toBeInTheDocument()
    })
    expect(screen.getByText(/查詢區間缺口/)).toBeInTheDocument()
    expect(screen.getByText(/最後取得時間/)).toBeInTheDocument()

    await user.click(screen.getByText('32100.5'))
    expect(screen.getByText('Typed detail')).toBeInTheDocument()
    expect(screen.getByText('ingested_at')).toBeInTheDocument()

    await user.click(screen.getByText('下一頁'))
    await waitFor(() => {
      expect(screen.getByText('30100')).toBeInTheDocument()
    })

    await user.click(screen.getByText('匯出 CSV'))
    expect(screen.getByText('匯出 CSV')).toBeInTheDocument()
  })

  it('lists Data Explorer datasets in the sidebar when the feature is enabled', async () => {
    renderPath('/')
    await waitFor(() => {
      expect(screen.getByRole('link', { name: '營運資料檢視器' })).toHaveAttribute('href', '/data')
    })
    expect(screen.getByRole('link', { name: '逐時用電負載' })).toHaveAttribute('href', '/data/power/load')
    expect(screen.getByRole('link', { name: '全台供需' })).toHaveAttribute('href', '/data/power/supply-demand')
    expect(screen.getByRole('link', { name: '區域供需' })).toHaveAttribute('href', '/data/power/regional')
    expect(screen.getByRole('link', { name: '機組發電' })).toHaveAttribute('href', '/data/power/units')
    expect(screen.getByRole('link', { name: 'CWA 測站觀測' })).toHaveAttribute('href', '/data/weather/observations')
    expect(screen.getByRole('link', { name: 'CWA 鄉鎮預報' })).toHaveAttribute('href', '/data/weather/forecasts')
    expect(screen.getByRole('link', { name: 'CWA 觀測批次審計' })).toHaveAttribute(
      'href',
      '/data/audits?type=observations',
    )
    expect(screen.getByRole('link', { name: 'CWA 預報版本審計' })).toHaveAttribute(
      'href',
      '/data/audits?type=forecasts',
    )
  })

  it('hides Data Explorer navigation when the feature is disabled', async () => {
    server.use(
      http.get('*/health', () =>
        HttpResponse.json({
          status: 'ok',
          version: '0.1.0',
          environment: 'aws',
          model_loaded: true,
          data_explorer_enabled: false,
        }),
      ),
    )
    renderPath('/')
    await waitFor(() => {
      expect(screen.getByText('即時預測總覽')).toBeInTheDocument()
    })
    await waitFor(() => {
      expect(screen.queryByText('營運資料檢視器')).not.toBeInTheDocument()
    })
    expect(screen.queryByRole('link', { name: '逐時用電負載' })).not.toBeInTheDocument()
    expect(screen.queryByRole('link', { name: 'CWA 觀測批次審計' })).not.toBeInTheDocument()
  })

  it('hides Data Explorer navigation when health is unavailable', async () => {
    server.use(http.get('*/health', () => HttpResponse.error()))
    renderPath('/')
    await waitFor(() => {
      expect(screen.getByText('即時預測總覽')).toBeInTheDocument()
    })
    expect(screen.queryByRole('link', { name: '營運資料檢視器' })).not.toBeInTheDocument()
    expect(screen.queryByRole('link', { name: '逐時用電負載' })).not.toBeInTheDocument()
  })

  it.each([
    [400, '分頁游標無效或已與目前篩選條件不相容。'],
    [422, '篩選條件無效，請確認時間範圍與欄位格式。'],
    [503, '資料庫目前無法連線，請稍後再試。'],
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

  it.each([
    ['/data/power/load', 'location=Taipei', 'location', 'Taipei'],
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

    expect(await screen.findByRole('button', { name: '回到第一頁' })).toBeInTheDocument()
    expect(requests).toHaveLength(1)
    expect(requests[0].searchParams.get('cursor')).toBe('old')

    await user.click(screen.getByRole('button', { name: '回到第一頁' }))
    await screen.findByText('查無符合資料，查詢成功但結果為空。')
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
      await user.click(screen.getByRole('button', { name: '下一頁' }))
      await screen.findByRole('button', { name: '回到第一頁' })
      expect(requests).toHaveLength(2)

      temperature = 31.5
      await user.click(screen.getByRole('button', { name: '回到第一頁' }))

      expect(await screen.findByText('31.5')).toBeInTheDocument()
      expect(screen.queryByText('27.5')).not.toBeInTheDocument()
      expect(requests).toHaveLength(3)
      expect(Object.fromEntries(requests[2].searchParams)).toEqual(Object.fromEntries(filters))
    },
  )

  it.each([400, 422, 503])('does not offer cursor recovery for an unrelated %s error', async (status) => {
    server.use(http.get('*/data/power/load', () => HttpResponse.json({ detail: 'failed' }, { status })))
    renderPath(`/data/power/load?${status === 400 ? '' : 'cursor=old'}`)

    await screen.findByText(status === 400
      ? '分頁游標無效或已與目前篩選條件不相容。'
      : status === 422
        ? '篩選條件無效，請確認時間範圍與欄位格式。'
        : '資料庫目前無法連線，請稍後再試。', {}, { timeout: status === 503 ? 2500 : 1000 })
    expect(screen.queryByRole('button', { name: '回到第一頁' })).not.toBeInTheDocument()
  })
})

describe('Monitoring Data Source Status', () => {
  it('uses the shared status contract and deep-links into Data Explorer', async () => {
    renderPath('/monitoring')
    await waitFor(() => {
      expect(screen.getByText('Data Source Status')).toBeInTheDocument()
      expect(screen.getAllByText('開啟 Explorer').length).toBeGreaterThan(0)
    })
    const regionalLink = screen.getAllByText('開啟 Explorer').find((node) =>
      node.getAttribute('href')?.includes('completeness=incomplete'),
    )
    expect(regionalLink).toBeDefined()
    expect(screen.queryByText(/Feast Feature Store/)).not.toBeInTheDocument()
    expect(screen.queryByText(/Feature Store Snapshot/)).not.toBeInTheDocument()
  })

  it('hides explorer links when Data Explorer is disabled', async () => {
    server.use(
      http.get('*/health', () =>
        HttpResponse.json({
          status: 'ok',
          version: '0.1.0',
          environment: 'aws',
          model_loaded: true,
          data_explorer_enabled: false,
        }),
      ),
    )
    renderPath('/monitoring')
    await waitFor(() => {
      expect(screen.getAllByText('Explorer 未啟用').length).toBeGreaterThan(0)
    })
    expect(screen.queryByText('開啟 Explorer')).not.toBeInTheDocument()
  })
})

describe('CWA observation explorer', () => {
  it('shows latest audit fetch time and missing identifiers', async () => {
    renderPath('/data/weather/observations')
    await waitFor(() => {
      expect(screen.getByText(/最新 audit/)).toBeInTheDocument()
    })
    expect(screen.getAllByText(/466920/).length).toBeGreaterThan(0)
    expect(screen.getByText('Audit History')).toBeInTheDocument()
  })
})
