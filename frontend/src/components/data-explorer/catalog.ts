export interface ExplorerColumn {
  key: string
  label: string
}

export interface ExplorerFilterField {
  key: string
  label: string
  placeholder?: string
}

export interface ExplorerDatasetConfig {
  id: string
  label: string
  description: string
  path: string
  navGroup: ExplorerNavGroup
  apiPath: string
  columns: ExplorerColumn[]
  filters: ExplorerFilterField[]
  defaultHours: number
  lookAheadHours?: number
  search?: Record<string, string>
  auditHref?: string
  auditLabel?: string
  auditDatasetId?: string
}

export const EXPLORER_NAV_GROUPS = [
  { id: 'power', label: 'Power' },
  { id: 'weather', label: 'Weather' },
  { id: 'audit', label: 'Audits' },
] as const

export type ExplorerNavGroup = (typeof EXPLORER_NAV_GROUPS)[number]['id']

export const EXPLORER_DATASETS: ExplorerDatasetConfig[] = [
  {
    id: 'hourly_load',
    label: '逐時用電負載',
    description: '已入庫的台電逐時負載，供模型訓練來源查驗。',
    path: '/data/power/load',
    navGroup: 'power',
    apiPath: '/data/power/load',
    defaultHours: 24,
    columns: [
      { key: 'datetime', label: '時間' },
      { key: 'subject', label: 'Prediction subject' },
      { key: 'load_mw', label: '負載 (MW)' },
    ],
    filters: [{ key: 'subject', label: 'Prediction subject', placeholder: 'nationwide' }],
  },
  {
    id: 'national_supply_demand',
    label: '全台供需',
    description: '全台目前負載、使用率與備轉資訊快照。',
    path: '/data/power/supply-demand',
    navGroup: 'power',
    apiPath: '/data/power/supply-demand',
    defaultHours: 24,
    columns: [
      { key: 'observed_at', label: '觀測時間' },
      { key: 'curr_load_mw', label: '目前負載 (MW)' },
      { key: 'curr_util_rate_pct', label: '使用率 (%)' },
    ],
    filters: [],
  },
  {
    id: 'regional_supply_demand',
    label: '區域供需',
    description: '北中南東四區發電與用電快照。',
    path: '/data/power/regional',
    navGroup: 'power',
    apiPath: '/data/power/regional',
    defaultHours: 24,
    columns: [
      { key: 'observed_at', label: '觀測時間' },
      { key: 'region', label: '區域' },
      { key: 'load_mw', label: '用電 (MW)' },
      { key: 'generation_mw', label: '發電 (MW)' },
      { key: 'slot_complete', label: 'Slot 完整' },
    ],
    filters: [
      { key: 'region', label: '區域', placeholder: '北部' },
      { key: 'completeness', label: '完整度', placeholder: 'complete | incomplete' },
    ],
  },
  {
    id: 'unit_generation',
    label: '機組發電',
    description: '各機組即時淨發電量、容量與備註。',
    path: '/data/power/units',
    navGroup: 'power',
    apiPath: '/data/power/units',
    defaultHours: 24,
    columns: [
      { key: 'observed_at', label: '觀測時間' },
      { key: 'unit_type', label: '機組類型' },
      { key: 'unit_name', label: '機組名稱' },
      { key: 'net_generation_mw', label: '淨發電 (MW)' },
    ],
    filters: [
      { key: 'unit_type', label: '機組類型' },
      { key: 'unit_name', label: '機組名稱' },
    ],
  },
  {
    id: 'cwa_observations',
    label: 'CWA 測站觀測',
    description: 'Canonical 測站觀測與逐時缺口。',
    path: '/data/weather/observations',
    navGroup: 'weather',
    apiPath: '/data/weather/observations',
    defaultHours: 24,
    auditHref: '/data/audits?type=observations',
    auditLabel: 'Audit History',
    auditDatasetId: 'cwa_observation_audits',
    columns: [
      { key: 'observed_at', label: '觀測時間' },
      { key: 'station_id', label: '測站' },
      { key: 'temperature_c', label: '氣溫 (°C)' },
      { key: 'relative_humidity_pct', label: '相對濕度 (%)' },
    ],
    filters: [{ key: 'station_id', label: '測站編號', placeholder: '466920' }],
  },
  {
    id: 'cwa_forecasts',
    label: 'CWA 鄉鎮預報',
    description: '所有已保存 forecast vintages；預設最新發布版本。',
    path: '/data/weather/forecasts',
    navGroup: 'weather',
    apiPath: '/data/weather/forecasts',
    defaultHours: 1,
    lookAheadHours: 72,
    auditHref: '/data/audits?type=forecasts',
    auditLabel: 'Audit History',
    auditDatasetId: 'cwa_forecast_audits',
    columns: [
      { key: 'valid_from', label: '有效時間' },
      { key: 'geocode', label: 'Geocode' },
      { key: 'dataset_id', label: '資料集' },
      { key: 'temperature_c', label: '氣溫 (°C)' },
      { key: 'issued_at', label: '發布時間' },
    ],
    filters: [
      { key: 'dataset_id', label: '資料集', placeholder: 'F-D0047-089' },
      { key: 'geocode', label: 'Geocode', placeholder: '63000000' },
      { key: 'issued_at', label: '發布時間' },
      { key: 'source_updated_at', label: '來源更新時間' },
      { key: 'all_vintages', label: '全部版本', placeholder: 'true' },
    ],
  },
  {
    id: 'cwa_observation_audits',
    label: 'CWA 觀測批次審計',
    description: 'Observation batch 完整／不完整歷史，不含 raw payload。',
    path: '/data/audits',
    navGroup: 'audit',
    search: { type: 'observations' },
    apiPath: '/data/audits/cwa-observations',
    defaultHours: 24,
    columns: [
      { key: 'fetched_at', label: '擷取時間' },
      { key: 'status', label: '狀態' },
      { key: 'missing_station_ids', label: '缺少測站' },
    ],
    filters: [
      { key: 'status', label: '狀態', placeholder: 'complete | incomplete' },
      { key: 'missing_station_id', label: '缺少測站編號' },
    ],
  },
  {
    id: 'cwa_forecast_audits',
    label: 'CWA 預報版本審計',
    description: 'Forecast release 版本與缺少行政區歷史，不含 raw payload。',
    path: '/data/audits',
    navGroup: 'audit',
    search: { type: 'forecasts' },
    apiPath: '/data/audits/cwa-forecasts',
    defaultHours: 24,
    columns: [
      { key: 'issued_at', label: '發布時間' },
      { key: 'dataset_id', label: '資料集' },
      { key: 'status', label: '狀態' },
      { key: 'missing_geocodes', label: '缺少 Geocode' },
    ],
    filters: [
      { key: 'dataset_id', label: '資料集' },
      { key: 'status', label: '狀態', placeholder: 'complete | incomplete' },
      { key: 'missing_geocode', label: '缺少 Geocode' },
    ],
  },
]

export function datasetById(id: string): ExplorerDatasetConfig {
  const dataset = EXPLORER_DATASETS.find((item) => item.id === id)
  if (!dataset) throw new Error(`Unknown dataset: ${id}`)
  return dataset
}
