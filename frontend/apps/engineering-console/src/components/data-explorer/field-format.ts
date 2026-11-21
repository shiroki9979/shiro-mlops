import { EMPTY_VALUE, formatCalendarDate, formatNumber, formatTimestamp } from '@shiro-mlops/shared/i18n/format'
import type { Locale } from '@shiro-mlops/shared/i18n/locale-store'
import type { Messages } from '@/i18n/messages'
import type { ExplorerFieldKey } from './catalog'
import { translateCompleteness } from './status-text'

// 'text' covers identifiers and data values (station IDs, geocodes, regions, unit names): shown verbatim.
export type FieldKind = 'timestamp' | 'date' | 'measurement' | 'flag' | 'auditStatus' | 'text'

// Classified by field meaning rather than by value shape: station IDs and geocodes are numeric-looking
// strings that must never be grouped like measurements. The Record type forces every dictionary key here.
const FIELD_KINDS: Record<ExplorerFieldKey, FieldKind> = {
  datetime: 'timestamp',
  ingested_at: 'timestamp',
  observed_at: 'timestamp',
  source_publish_time: 'timestamp',
  source_time: 'timestamp',
  real_hr_peak_time: 'timestamp',
  issued_at: 'timestamp',
  source_updated_at: 'timestamp',
  valid_from: 'timestamp',
  valid_to: 'timestamp',
  fetched_at: 'timestamp',
  yday_date: 'date',
  load_mw: 'measurement',
  load_wan_kw: 'measurement',
  curr_load_mw: 'measurement',
  curr_load_wan_kw: 'measurement',
  curr_util_rate_pct: 'measurement',
  fore_maxi_sply_capacity_mw: 'measurement',
  fore_maxi_sply_capacity_wan_kw: 'measurement',
  fore_peak_dema_load_mw: 'measurement',
  fore_peak_dema_load_wan_kw: 'measurement',
  fore_peak_resv_capacity_mw: 'measurement',
  fore_peak_resv_capacity_wan_kw: 'measurement',
  fore_peak_resv_rate_pct: 'measurement',
  yday_maxi_sply_capacity_mw: 'measurement',
  yday_maxi_sply_capacity_wan_kw: 'measurement',
  yday_peak_dema_load_mw: 'measurement',
  yday_peak_dema_load_wan_kw: 'measurement',
  yday_peak_resv_capacity_mw: 'measurement',
  yday_peak_resv_capacity_wan_kw: 'measurement',
  yday_peak_resv_rate_pct: 'measurement',
  real_hr_maxi_sply_capacity_mw: 'measurement',
  real_hr_maxi_sply_capacity_wan_kw: 'measurement',
  generation_mw: 'measurement',
  generation_wan_kw: 'measurement',
  capacity_mw: 'measurement',
  net_generation_mw: 'measurement',
  capacity_ratio_pct: 'measurement',
  temperature_c: 'measurement',
  dew_point_c: 'measurement',
  apparent_temperature_c: 'measurement',
  relative_humidity_pct: 'measurement',
  probability_of_precipitation_pct: 'measurement',
  air_pressure_hpa: 'measurement',
  precipitation_mm: 'measurement',
  wind_speed_m_s: 'measurement',
  wind_direction_deg: 'measurement',
  batch_count: 'measurement',
  version_count: 'measurement',
  slot_complete: 'flag',
  status: 'auditStatus',
  subject: 'text',
  region: 'text',
  missing_regions: 'text',
  completeness: 'text',
  unit_type: 'text',
  unit_name: 'text',
  remark: 'text',
  station_id: 'text',
  station_name: 'text',
  town_code: 'text',
  wind_direction: 'text',
  dataset_id: 'text',
  geocode: 'text',
  location_name: 'text',
  all_vintages: 'text',
  missing_station_ids: 'text',
  missing_station_id: 'text',
  missing_geocodes: 'text',
  missing_geocode: 'text',
  fore_peak_resv_indicator: 'text',
  fore_peak_hour_range: 'text',
  yday_peak_resv_indicator: 'text',
}

export interface FieldFormatContext {
  locale: Locale
  m: Messages
}

function isKnownField(key: string): key is ExplorerFieldKey {
  return Object.hasOwn(FIELD_KINDS, key)
}

export function explorerFieldKind(key: string): FieldKind {
  return isKnownField(key) ? FIELD_KINDS[key] : 'text'
}

export function explorerFieldLabel(key: string, m: Messages): string {
  return isKnownField(key) ? m.explorer.fields[key] : key
}

export function formatExplorerField(key: string, value: unknown, context: FieldFormatContext): string {
  if (value === null || value === undefined || value === '') return EMPTY_VALUE
  return formatByKind(explorerFieldKind(key), value, context)
}

function formatByKind(kind: FieldKind, value: unknown, { locale, m }: FieldFormatContext): string {
  if (kind === 'timestamp' && typeof value === 'string') return formatTimestamp(value, locale)
  if (kind === 'date' && typeof value === 'string') return formatCalendarDate(value, locale)
  if (kind === 'measurement' && typeof value === 'number') return formatNumber(value, locale)
  if (kind === 'flag' && typeof value === 'boolean') return value ? m.common.yes : m.common.no
  if (kind === 'auditStatus') return translateCompleteness(String(value), m)
  return formatVerbatim(value)
}

function formatVerbatim(value: unknown): string {
  if (Array.isArray(value)) return value.join(', ')
  return String(value)
}
