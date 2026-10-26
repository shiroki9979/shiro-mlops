import type { Locale } from './locale-store'

// Grid data is defined in Taipei time; following the browser time zone would shift every hour label abroad.
export const TAIPEI_TIME_ZONE = 'Asia/Taipei'

const SHORT_DATE_TIME: Intl.DateTimeFormatOptions = {
  month: '2-digit',
  day: '2-digit',
  hour: '2-digit',
  minute: '2-digit',
  hourCycle: 'h23',
  timeZone: TAIPEI_TIME_ZONE,
}

const FULL_TIMESTAMP: Intl.DateTimeFormatOptions = {
  year: 'numeric',
  month: '2-digit',
  day: '2-digit',
  hour: '2-digit',
  minute: '2-digit',
  second: '2-digit',
  hourCycle: 'h23',
  timeZone: TAIPEI_TIME_ZONE,
}

const CALENDAR_DATE: Intl.DateTimeFormatOptions = {
  year: 'numeric',
  month: '2-digit',
  day: '2-digit',
  timeZone: TAIPEI_TIME_ZONE,
}

const MAX_MEASUREMENT_FRACTION_DIGITS = 3

type DateInput = string | number | Date

function formatDate(value: DateInput, locale: Locale, options: Intl.DateTimeFormatOptions): string {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return String(value)
  return new Intl.DateTimeFormat(locale, options).format(date)
}

export function formatDateTime(value: DateInput, locale: Locale): string {
  return formatDate(value, locale, SHORT_DATE_TIME)
}

export function formatTimestamp(value: DateInput, locale: Locale): string {
  return formatDate(value, locale, FULL_TIMESTAMP)
}

// A bare YYYY-MM-DD names a Taipei calendar day, so it is anchored at Taipei midnight before formatting.
export function formatCalendarDate(isoDate: string, locale: Locale): string {
  return formatDate(`${isoDate}T00:00:00+08:00`, locale, CALENDAR_DATE)
}

export function formatNumber(value: number, locale: Locale): string {
  return new Intl.NumberFormat(locale, {
    maximumFractionDigits: MAX_MEASUREMENT_FRACTION_DIGITS,
  }).format(value)
}

export function formatLoadMW(value: number, locale: Locale): string {
  return new Intl.NumberFormat(locale, {
    maximumFractionDigits: 1,
    minimumFractionDigits: 1,
  }).format(value)
}

export function formatTemperature(value: number): string {
  return `${value.toFixed(1)}°C`
}
