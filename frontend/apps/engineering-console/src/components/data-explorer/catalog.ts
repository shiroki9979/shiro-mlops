import type { Messages } from '@/i18n/messages'
import type { CategoryPaletteKey } from '@/lib/chart-palette'
import { FORWARD_QUICK_RANGES, PAST_QUICK_RANGES, type QuickRangeId } from '@/lib/explorer-window'

// Display text lives in the locale dictionaries; ids and keys are typed against them so a missing entry fails tsc.
export type ExplorerDatasetId = keyof Messages['explorer']['datasets']
export type ExplorerFieldKey = keyof Messages['explorer']['fields']

// Fields without a control are free text: their value sets are open and no endpoint lists distinct values.
export type ExplorerFilterControl =
  | { kind: 'select'; options: readonly string[] }
  | { kind: 'switch' }

export interface ExplorerFilterField {
  key: ExplorerFieldKey
  // Placeholders show valid input values (data values), so they are not translated.
  placeholder?: string
  control?: ExplorerFilterControl
}

export type ExplorerChartType = 'line' | 'stackedArea'
export type ExplorerGroupOption = keyof Messages['explorer']['chart']['groupOptions']

// What a dataset supplies to get a chart card; bucketing, limits and gap bands are shared.
export interface ExplorerChartConfig {
  type: ExplorerChartType
  seriesApiPath: string
  // Default `fields`; a `fields` value already in the URL takes precedence.
  fields: ExplorerFieldKey[]
  // Group key whose values pick a colour from the central palette; others use series order.
  colorBy?: { group: string; palette: CategoryPaletteKey }
  // Selectable `group_by` values, the first being the API default that the URL leaves out.
  groupOptions?: readonly ExplorerGroupOption[]
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
  // SYNC(src/shiro_mlops/service/data_explorer/specs.py): DATASET_SPECS max_days, the list window limit the API enforces with 422.
  maxDays: number
  // SYNC(src/shiro_mlops/service/data_explorer/specs.py): DATASET_SPECS cadence, the length of a `raw` chart bucket.
  cadenceSeconds: number
  quickRanges: readonly QuickRangeId[]
  search?: Record<string, string>
  auditHref?: string
  auditDatasetId?: ExplorerDatasetId
  chart?: ExplorerChartConfig
}

export const EXPLORER_NAV_GROUPS = ['power', 'weather', 'audit'] as const satisfies ReadonlyArray<
  keyof Messages['explorer']['navGroups']
>

export type ExplorerNavGroup = (typeof EXPLORER_NAV_GROUPS)[number]

// SYNC(src/shiro_mlops/data/taipower_regional_supply_demand.py): REGIONAL_SUPPLY_DEMAND_REGIONS.
const REGIONS = ['北部', '中部', '南部', '東部'] as const
const COMPLETENESS_VALUES = ['complete', 'incomplete'] as const
const COMPLETENESS_SELECT: ExplorerFilterControl = { kind: 'select', options: COMPLETENESS_VALUES }

export const EXPLORER_DATASETS: ExplorerDatasetConfig[] = [
  {
    id: 'hourly_load',
    path: '/data/power/load',
    navGroup: 'power',
    apiPath: '/data/power/load',
    defaultHours: 24,
    maxDays: 31,
    cadenceSeconds: 3600,
    quickRanges: PAST_QUICK_RANGES,
    columns: ['datetime', 'subject', 'load_mw'],
    filters: [{ key: 'subject', placeholder: 'nationwide' }],
    chart: { type: 'line', seriesApiPath: '/data/power/load/series', fields: ['load_mw'] },
  },
  {
    id: 'national_supply_demand',
    path: '/data/power/supply-demand',
    navGroup: 'power',
    apiPath: '/data/power/supply-demand',
    defaultHours: 24,
    maxDays: 7,
    cadenceSeconds: 600,
    quickRanges: PAST_QUICK_RANGES,
    columns: ['observed_at', 'curr_load_mw', 'curr_util_rate_pct'],
    filters: [],
  },
  {
    id: 'regional_supply_demand',
    path: '/data/power/regional',
    navGroup: 'power',
    apiPath: '/data/power/regional',
    defaultHours: 24,
    maxDays: 7,
    cadenceSeconds: 600,
    quickRanges: PAST_QUICK_RANGES,
    columns: ['observed_at', 'region', 'load_mw', 'generation_mw', 'slot_complete'],
    filters: [
      { key: 'region', control: { kind: 'select', options: REGIONS } },
      { key: 'completeness', control: COMPLETENESS_SELECT },
    ],
  },
  {
    id: 'unit_generation',
    path: '/data/power/units',
    navGroup: 'power',
    apiPath: '/data/power/units',
    defaultHours: 24,
    maxDays: 7,
    cadenceSeconds: 600,
    quickRanges: PAST_QUICK_RANGES,
    columns: ['observed_at', 'unit_type', 'unit_name', 'net_generation_mw'],
    filters: [{ key: 'unit_type' }, { key: 'unit_name' }],
    chart: {
      type: 'stackedArea',
      seriesApiPath: '/data/power/units/series',
      fields: ['net_generation_mw'],
      colorBy: { group: 'unit_type', palette: 'unit_type' },
      // SYNC(src/shiro_mlops/service/data_explorer/power.py): UnitGroupBy, default first.
      groupOptions: ['unit_type', 'none'],
    },
  },
  {
    id: 'cwa_observations',
    path: '/data/weather/observations',
    navGroup: 'weather',
    apiPath: '/data/weather/observations',
    defaultHours: 24,
    maxDays: 31,
    cadenceSeconds: 3600,
    quickRanges: PAST_QUICK_RANGES,
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
    maxDays: 14,
    cadenceSeconds: 3600,
    quickRanges: FORWARD_QUICK_RANGES,
    auditHref: '/data/audits?type=forecasts',
    auditDatasetId: 'cwa_forecast_audits',
    columns: ['valid_from', 'geocode', 'dataset_id', 'temperature_c', 'issued_at'],
    filters: [
      { key: 'dataset_id', placeholder: 'F-D0047-089' },
      { key: 'geocode', placeholder: '63000000' },
      { key: 'issued_at' },
      { key: 'source_updated_at' },
      { key: 'all_vintages', control: { kind: 'switch' } },
    ],
  },
  {
    id: 'cwa_observation_audits',
    path: '/data/audits',
    navGroup: 'audit',
    search: { type: 'observations' },
    apiPath: '/data/audits/cwa-observations',
    defaultHours: 24,
    maxDays: 31,
    cadenceSeconds: 3600,
    quickRanges: PAST_QUICK_RANGES,
    columns: ['fetched_at', 'status', 'missing_station_ids'],
    filters: [
      { key: 'status', control: COMPLETENESS_SELECT },
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
    maxDays: 31,
    cadenceSeconds: 3600,
    quickRanges: PAST_QUICK_RANGES,
    columns: ['issued_at', 'dataset_id', 'status', 'missing_geocodes'],
    filters: [
      { key: 'dataset_id' },
      { key: 'status', control: COMPLETENESS_SELECT },
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
