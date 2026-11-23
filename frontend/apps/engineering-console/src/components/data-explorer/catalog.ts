import type { Messages } from '@/i18n/messages'
import type { CategoryPaletteKey } from '@/lib/chart-palette'
import { FORWARD_QUICK_RANGES, PAST_QUICK_RANGES, type QuickRangeId } from '@/lib/explorer-window'
import type { ChartFieldOption } from './chart-fields'
import type { ExplorerValueLabels } from './status-text'

// Display text lives in the locale dictionaries; ids and keys are typed against them so a missing entry fails tsc.
export type ExplorerDatasetId = keyof Messages['explorer']['datasets']
export type ExplorerFieldKey = keyof Messages['explorer']['fields']

// Fields without a control are free text: their value sets are open and no endpoint lists distinct values.
export type ExplorerFilterControl =
  | { kind: 'select'; options: readonly string[]; optionLabels?: ExplorerValueLabels }
  | { kind: 'switch' }

export interface ExplorerFilterField {
  key: ExplorerFieldKey
  // Placeholders show valid input values (data values), so they are not translated.
  placeholder?: string
  control?: ExplorerFilterControl
}

export type ExplorerChartType = 'line' | 'status' | 'stackedArea'
export type ExplorerGroupOption = keyof Messages['explorer']['chart']['groupOptions']

// What a dataset supplies to get a chart card; bucketing, limits and gap bands are shared.
export interface ExplorerChartConfig {
  type: ExplorerChartType
  seriesApiPath: string
  // Default `fields`; URL `fields` among `fieldOptions` (or, without them, these) take precedence.
  fields: ExplorerFieldKey[]
  // Group key whose values pick a colour from the central palette; others use series order.
  colorBy?: { group: string; palette: CategoryPaletteKey }
  // `count`: the endpoint fixes its field and counts rows per bucket, so `fields` (here only the
  // label) and `agg` are never sent.
  measure?: 'count'
  // Group values with a dictionary entry are shown translated in the legend and tooltip.
  groupLabels?: ExplorerValueLabels
  // Selectable `group_by` values, the first being the API default that the URL leaves out.
  groupOptions?: readonly ExplorerGroupOption[]
  // Fields the user may chart (with their units); omitted or a single option shows no field picker.
  fieldOptions?: ChartFieldOption[]
  // Dataset filters the series endpoint accepts; omitted sends every declared filter.
  seriesFilters?: ExplorerFieldKey[]
  // Mark buckets where some, but not all, series are null (e.g. a region missing from a slot).
  markIncompleteBuckets?: boolean
  // Taipower publishes power in 萬瓩, so the tooltip also shows MW ÷ 10 for its MW series.
  tooltipWanKw?: boolean
  // While the `when` switch is on the chart needs the `filter` value, so no series is requested without it.
  requiredFilter?: { filter: ExplorerFieldKey; when: ExplorerFieldKey }
  // Group key holding an issue instant: such series are named by it and shaded newest first.
  vintageGroup?: string
  // The API returns only valued points (no gap-fill), so lines join across instants they lack.
  sparsePoints?: boolean
}

// The `/data` home card's 24-hour preview. A `count` chart becomes an hourly status grid and
// needs no settings; other charts draw `fields` (and `groupBy`) as a sparkline.
export interface ExplorerSparklineConfig {
  fields?: ExplorerFieldKey[]
  groupBy?: ExplorerGroupOption
  // Forecasts preview the next 24 hours of valid time instead of the last 24.
  forward?: boolean
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
  // SYNC(src/shiro_mlops/service/data_explorer/datasets/power.py, src/shiro_mlops/service/data_explorer/datasets/weather.py, src/shiro_mlops/service/data_explorer/datasets/audits.py): each Dataset's max_days, the list window limit the API enforces with 422.
  maxDays: number
  // SYNC(src/shiro_mlops/service/data_explorer/datasets/power.py, src/shiro_mlops/service/data_explorer/datasets/weather.py, src/shiro_mlops/service/data_explorer/datasets/audits.py): each Dataset's cadence, the length of a `raw` chart bucket.
  cadenceSeconds: number
  quickRanges: readonly QuickRangeId[]
  search?: Record<string, string>
  auditHref?: string
  auditDatasetId?: ExplorerDatasetId
  chart?: ExplorerChartConfig
  sparkline?: ExplorerSparklineConfig
}

export const EXPLORER_NAV_GROUPS = ['power', 'weather', 'audit'] as const satisfies ReadonlyArray<
  keyof Messages['explorer']['navGroups']
>

export type ExplorerNavGroup = (typeof EXPLORER_NAV_GROUPS)[number]

// SYNC(src/shiro_mlops/data/taipower_regional_supply_demand.py): REGIONAL_SUPPLY_DEMAND_REGIONS.
export const REGIONS = ['北部', '中部', '南部', '東部'] as const
export type ExplorerRegion = (typeof REGIONS)[number]
const COMPLETENESS_VALUES = ['complete', 'incomplete'] as const
const COMPLETENESS_SELECT: ExplorerFilterControl = {
  kind: 'select',
  options: COMPLETENESS_VALUES,
  optionLabels: 'completeness',
}

function auditStatusChart(seriesApiPath: string, countField: ExplorerFieldKey): ExplorerChartConfig {
  return {
    type: 'status',
    seriesApiPath,
    fields: [countField],
    colorBy: { group: 'status', palette: 'status' },
    measure: 'count',
    groupLabels: 'completeness',
  }
}

export const POWER_UNIT = 'MW'
const PERCENT_UNIT = '%'
// SYNC(src/shiro_mlops/service/data_explorer/datasets/power.py): NationalSeriesField and its units.
const NATIONAL_FIELD_OPTIONS: ChartFieldOption[] = [
  { field: 'curr_load_mw', unit: POWER_UNIT },
  { field: 'real_hr_maxi_sply_capacity_mw', unit: POWER_UNIT },
  { field: 'curr_util_rate_pct', unit: PERCENT_UNIT },
  { field: 'fore_maxi_sply_capacity_mw', unit: POWER_UNIT },
  { field: 'fore_peak_dema_load_mw', unit: POWER_UNIT },
  { field: 'fore_peak_resv_capacity_mw', unit: POWER_UNIT },
  { field: 'fore_peak_resv_rate_pct', unit: PERCENT_UNIT },
  { field: 'yday_maxi_sply_capacity_mw', unit: POWER_UNIT },
  { field: 'yday_peak_dema_load_mw', unit: POWER_UNIT },
  { field: 'yday_peak_resv_capacity_mw', unit: POWER_UNIT },
  { field: 'yday_peak_resv_rate_pct', unit: PERCENT_UNIT },
]
// SYNC(src/shiro_mlops/service/data_explorer/datasets/power.py): RegionalSeriesField and its units.
const REGIONAL_FIELD_OPTIONS: ChartFieldOption[] = [
  { field: 'load_mw', unit: POWER_UNIT },
  { field: 'generation_mw', unit: POWER_UNIT },
]

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
    sparkline: { fields: ['load_mw'] },
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
    chart: {
      type: 'line',
      seriesApiPath: '/data/power/supply-demand/series',
      fields: ['curr_load_mw', 'real_hr_maxi_sply_capacity_mw'],
      fieldOptions: NATIONAL_FIELD_OPTIONS,
      tooltipWanKw: true,
    },
    sparkline: { fields: ['curr_load_mw'] },
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
    chart: {
      type: 'line',
      seriesApiPath: '/data/power/regional/series',
      fields: ['load_mw'],
      fieldOptions: REGIONAL_FIELD_OPTIONS,
      colorBy: { group: 'region', palette: 'region' },
      // Completeness filters table rows; the chart shows every slot and marks incomplete ones instead.
      seriesFilters: ['region'],
      markIncompleteBuckets: true,
      tooltipWanKw: true,
    },
    sparkline: { fields: ['load_mw'] },
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
      // SYNC(src/shiro_mlops/service/data_explorer/datasets/power.py): UnitGroupBy, default first.
      groupOptions: ['unit_type', 'none'],
    },
    sparkline: { fields: ['net_generation_mw'], groupBy: 'none' },
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
    chart: {
      type: 'line',
      seriesApiPath: '/data/weather/observations/series',
      fields: ['temperature_c'],
      colorBy: { group: 'station_id', palette: 'station_id' },
    },
    sparkline: { fields: ['temperature_c'] },
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
    chart: {
      type: 'line',
      seriesApiPath: '/data/weather/forecasts/series',
      fields: ['temperature_c'],
      requiredFilter: { filter: 'geocode', when: 'all_vintages' },
      vintageGroup: 'issued_at',
      sparsePoints: true,
    },
    // Without a version filter the series endpoint returns the latest release, one line per geocode.
    sparkline: { fields: ['temperature_c'], forward: true },
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
    chart: auditStatusChart('/data/audits/cwa-observations/series', 'batch_count'),
    sparkline: {},
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
    chart: auditStatusChart('/data/audits/cwa-forecasts/series', 'version_count'),
    sparkline: {},
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
