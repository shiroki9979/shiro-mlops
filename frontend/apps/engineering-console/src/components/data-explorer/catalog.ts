import type { Messages } from '@/i18n/messages'

// Display text lives in the locale dictionaries; ids and keys are typed against them so a missing entry fails tsc.
export type ExplorerDatasetId = keyof Messages['explorer']['datasets']
export type ExplorerFieldKey = keyof Messages['explorer']['fields']

export interface ExplorerFilterField {
  key: ExplorerFieldKey
  // Placeholders show valid input values (data values), so they are not translated.
  placeholder?: string
}

export interface ExplorerDatasetConfig {
  id: ExplorerDatasetId
  path: string
  navGroup: ExplorerNavGroup
  apiPath: string
  columns: ExplorerFieldKey[]
  filters: ExplorerFilterField[]
  defaultHours: number
  lookAheadHours?: number
  search?: Record<string, string>
  auditHref?: string
  auditDatasetId?: ExplorerDatasetId
}

export const EXPLORER_NAV_GROUPS = ['power', 'weather', 'audit'] as const satisfies ReadonlyArray<
  keyof Messages['explorer']['navGroups']
>

export type ExplorerNavGroup = (typeof EXPLORER_NAV_GROUPS)[number]

export const EXPLORER_DATASETS: ExplorerDatasetConfig[] = [
  {
    id: 'hourly_load',
    path: '/data/power/load',
    navGroup: 'power',
    apiPath: '/data/power/load',
    defaultHours: 24,
    columns: ['datetime', 'subject', 'load_mw'],
    filters: [{ key: 'subject', placeholder: 'nationwide' }],
  },
  {
    id: 'national_supply_demand',
    path: '/data/power/supply-demand',
    navGroup: 'power',
    apiPath: '/data/power/supply-demand',
    defaultHours: 24,
    columns: ['observed_at', 'curr_load_mw', 'curr_util_rate_pct'],
    filters: [],
  },
  {
    id: 'regional_supply_demand',
    path: '/data/power/regional',
    navGroup: 'power',
    apiPath: '/data/power/regional',
    defaultHours: 24,
    columns: ['observed_at', 'region', 'load_mw', 'generation_mw', 'slot_complete'],
    filters: [
      { key: 'region', placeholder: '北部' },
      { key: 'completeness', placeholder: 'complete | incomplete' },
    ],
  },
  {
    id: 'unit_generation',
    path: '/data/power/units',
    navGroup: 'power',
    apiPath: '/data/power/units',
    defaultHours: 24,
    columns: ['observed_at', 'unit_type', 'unit_name', 'net_generation_mw'],
    filters: [{ key: 'unit_type' }, { key: 'unit_name' }],
  },
  {
    id: 'cwa_observations',
    path: '/data/weather/observations',
    navGroup: 'weather',
    apiPath: '/data/weather/observations',
    defaultHours: 24,
    auditHref: '/data/audits?type=observations',
    auditDatasetId: 'cwa_observation_audits',
    columns: ['observed_at', 'station_id', 'temperature_c', 'relative_humidity_pct'],
    filters: [{ key: 'station_id', placeholder: '466920' }],
  },
  {
    id: 'cwa_forecasts',
    path: '/data/weather/forecasts',
    navGroup: 'weather',
    apiPath: '/data/weather/forecasts',
    defaultHours: 1,
    lookAheadHours: 72,
    auditHref: '/data/audits?type=forecasts',
    auditDatasetId: 'cwa_forecast_audits',
    columns: ['valid_from', 'geocode', 'dataset_id', 'temperature_c', 'issued_at'],
    filters: [
      { key: 'dataset_id', placeholder: 'F-D0047-089' },
      { key: 'geocode', placeholder: '63000000' },
      { key: 'issued_at' },
      { key: 'source_updated_at' },
      { key: 'all_vintages', placeholder: 'true' },
    ],
  },
  {
    id: 'cwa_observation_audits',
    path: '/data/audits',
    navGroup: 'audit',
    search: { type: 'observations' },
    apiPath: '/data/audits/cwa-observations',
    defaultHours: 24,
    columns: ['fetched_at', 'status', 'missing_station_ids'],
    filters: [
      { key: 'status', placeholder: 'complete | incomplete' },
      { key: 'missing_station_id' },
    ],
  },
  {
    id: 'cwa_forecast_audits',
    path: '/data/audits',
    navGroup: 'audit',
    search: { type: 'forecasts' },
    apiPath: '/data/audits/cwa-forecasts',
    defaultHours: 24,
    columns: ['issued_at', 'dataset_id', 'status', 'missing_geocodes'],
    filters: [
      { key: 'dataset_id' },
      { key: 'status', placeholder: 'complete | incomplete' },
      { key: 'missing_geocode' },
    ],
  },
]

export function isExplorerDatasetId(id: string): id is ExplorerDatasetId {
  return EXPLORER_DATASETS.some((dataset) => dataset.id === id)
}

export function datasetById(id: ExplorerDatasetId): ExplorerDatasetConfig {
  const dataset = EXPLORER_DATASETS.find((item) => item.id === id)
  if (!dataset) throw new Error(`Unknown dataset: ${id}`)
  return dataset
}
