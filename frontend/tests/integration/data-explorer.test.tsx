import { describe, expect, it } from 'vitest'
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
