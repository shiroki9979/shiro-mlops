import { http, HttpResponse } from 'msw'

export function generateMockPredictions(horizon = 24) {
  const baseTime = new Date()
  baseTime.setMinutes(0, 0, 0)
  const predictions = []

  for (let i = 1; i <= horizon; i++) {
    const dt = new Date(baseTime.getTime() + i * 3600000)
    const hour = dt.getHours()
    const cycle = Math.sin(((hour - 6) / 24) * 2 * Math.PI)
    const load = 28500 + cycle * 7200 + (i * 20)
    const temp = 26 + cycle * 6 + (Math.random() * 0.5)
    const humidity = 70 - cycle * 15

    predictions.push({
      datetime: dt.toISOString(),
      predicted_load_mw: parseFloat(load.toFixed(1)),
      temperature: parseFloat(temp.toFixed(1)),
      relative_humidity: parseFloat(humidity.toFixed(1)),
    })
  }

  return {
    status: 'success',
    horizon_hours: horizon,
    subject: 'nationwide',
    predictions,
  }
}

const statusPayload = {
  timezone: 'Asia/Taipei',
  datasets: [
    {
      id: 'hourly_load',
      label: '逐時用電負載',
      availability: 'available',
      freshness: 'fresh',
      completeness: 'incomplete',
      overall: 'warning',
      latest_source_at: '2026-09-09T20:00:00+08:00',
      latest_ingested_at: '2026-09-09T20:01:00+08:00',
      ingestion_age_seconds: 120,
      source_age_seconds: 180,
      missing_identifiers: ['2026-09-09T19:00:00+08:00'],
      missing_slot_count: 1,
      href: '/data/power/load',
    },
    {
      id: 'national_supply_demand',
      label: '全台供需',
      availability: 'available',
      freshness: 'fresh',
      completeness: 'complete',
      overall: 'healthy',
      latest_source_at: '2026-09-09T20:00:00+08:00',
      latest_ingested_at: '2026-09-09T20:00:30+08:00',
      ingestion_age_seconds: 90,
      source_age_seconds: 120,
      missing_identifiers: [],
      missing_slot_count: 0,
      href: '/data/power/supply-demand',
    },
    {
      id: 'cwa_forecasts',
      label: 'CWA 鄉鎮預報',
      availability: 'available',
      freshness: 'fresh',
      completeness: 'complete',
      overall: 'healthy',
      latest_source_at: '2026-09-09T19:40:00+08:00',
      latest_ingested_at: '2026-09-09T19:41:00+08:00',
      ingestion_age_seconds: 300,
      source_age_seconds: 360,
      latest_release_stale: false,
      missing_identifiers: [],
      missing_slot_count: 0,
      href: '/data/weather/forecasts',
    },
    {
      id: 'regional_supply_demand',
      label: '區域供需',
      availability: 'available',
      freshness: 'warning',
      completeness: 'incomplete',
      overall: 'warning',
      latest_source_at: '2026-09-09T20:00:00+08:00',
      latest_ingested_at: '2026-09-09T20:00:20+08:00',
      ingestion_age_seconds: 110,
      source_age_seconds: 150,
      missing_identifiers: ['東部'],
      missing_slot_count: 1,
      href: '/data/power/regional?completeness=incomplete',
    },
    {
      id: 'cwa_observations',
      label: 'CWA 測站觀測',
      availability: 'available',
      freshness: 'fresh',
      completeness: 'incomplete',
      overall: 'warning',
      latest_source_at: '2026-09-09T20:00:00+08:00',
      latest_ingested_at: '2026-09-09T20:02:00+08:00',
      ingestion_age_seconds: 80,
      source_age_seconds: 140,
      missing_identifiers: ['466920'],
      missing_slot_count: 1,
      href: '/data/weather/observations',
    },
    {
      id: 'cwa_observation_audits',
      label: 'CWA 觀測批次審計',
      availability: 'available',
      freshness: 'fresh',
      completeness: 'incomplete',
      overall: 'warning',
      latest_source_at: '2026-09-09T20:02:00+08:00',
      latest_ingested_at: '2026-09-09T20:02:00+08:00',
      ingestion_age_seconds: 80,
      source_age_seconds: 80,
      missing_identifiers: ['466920'],
      missing_slot_count: 1,
      href: '/data/audits?type=observations',
    },
  ],
}

const loadEnvelope = {
  timezone: 'Asia/Taipei',
  items: [
    {
      datetime: '2026-09-09T20:00:00+08:00',
      subject: 'nationwide',
      load_mw: 32100.5,
      ingested_at: '2026-09-09T20:01:00+08:00',
    },
  ],
  next_cursor: 'cursor-page-2',
  has_more: true,
  missing_slots: ['2026-09-09T19:00:00+08:00'],
}

export const handlers = [
  http.get('*/health', () => {
    return HttpResponse.json({
      status: 'ok',
      version: '0.1.0',
      environment: 'local',
      model_loaded: true,
      data_explorer_enabled: true,
    })
  }),

  http.post('*/predict', async ({ request }) => {
    const body = (await request.json()) as {
      horizon_hours?: number
    }
    const horizon = body?.horizon_hours || 24
    return HttpResponse.json(generateMockPredictions(horizon))
  }),

  http.get('*/data/status', () => HttpResponse.json(statusPayload)),

  http.get('*/data/power/load', ({ request }) => {
    const url = new URL(request.url)
    if (url.searchParams.get('cursor') === 'cursor-page-2') {
      return HttpResponse.json({
        ...loadEnvelope,
        items: [
          {
            datetime: '2026-09-09T18:00:00+08:00',
            subject: 'nationwide',
            load_mw: 30100.0,
            ingested_at: '2026-09-09T18:01:00+08:00',
          },
        ],
        next_cursor: null,
        has_more: false,
      })
    }
    return HttpResponse.json(loadEnvelope)
  }),

  http.get('*/data/power/supply-demand', () =>
    HttpResponse.json({
      timezone: 'Asia/Taipei',
      items: [
        {
          observed_at: '2026-09-09T20:00:00+08:00',
          curr_load_mw: 32421,
          curr_load_wan_kw: 3242.1,
          curr_util_rate_pct: 78,
        },
      ],
      next_cursor: null,
      has_more: false,
      missing_slots: [],
    }),
  ),

  http.get('*/data/power/regional', () =>
    HttpResponse.json({ timezone: 'Asia/Taipei', items: [], next_cursor: null, has_more: false, missing_slots: [] }),
  ),
  http.get('*/data/power/units', () =>
    HttpResponse.json({ timezone: 'Asia/Taipei', items: [], next_cursor: null, has_more: false, missing_slots: [] }),
  ),
  http.get('*/data/weather/observations', () =>
    HttpResponse.json({ timezone: 'Asia/Taipei', items: [], next_cursor: null, has_more: false, missing_slots: [] }),
  ),
  http.get('*/data/weather/forecasts', () =>
    HttpResponse.json({ timezone: 'Asia/Taipei', items: [], next_cursor: null, has_more: false, missing_slots: [] }),
  ),
  http.get('*/data/audits/cwa-observations', () =>
    HttpResponse.json({ timezone: 'Asia/Taipei', items: [], next_cursor: null, has_more: false, missing_slots: [] }),
  ),
  http.get('*/data/audits/cwa-forecasts', () =>
    HttpResponse.json({ timezone: 'Asia/Taipei', items: [], next_cursor: null, has_more: false, missing_slots: [] }),
  ),
]
