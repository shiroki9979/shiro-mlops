import { formatHumidity, formatLoadMW, formatNumber, formatTemperature } from '@/i18n/format'
import type { Locale } from '@/i18n/locale-store'

type SeriesFormatter = (value: number, locale: Locale) => string

// Units follow the plotted field, not the translated series name.
const SERIES_FORMATTERS = {
  predicted_load_mw: (value, locale) => `${formatLoadMW(value, locale)} MW`,
  temperature: formatTemperature,
  relative_humidity: formatHumidity,
} satisfies Record<string, SeriesFormatter>

type SeriesKey = keyof typeof SERIES_FORMATTERS

function isSeriesKey(dataKey: string | number | undefined): dataKey is SeriesKey {
  return typeof dataKey === 'string' && Object.hasOwn(SERIES_FORMATTERS, dataKey)
}

export function formatSeriesValue(dataKey: string | number | undefined, value: number, locale: Locale): string {
  if (isSeriesKey(dataKey)) return SERIES_FORMATTERS[dataKey](value, locale)
  return formatNumber(value, locale)
}
