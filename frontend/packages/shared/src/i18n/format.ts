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
const LOAD_MW_FRACTION_DIGITS = 1
const TEMPERATURE_FRACTION_DIGITS = 1
const HUMIDITY_FRACTION_DIGITS = 1
const MW_PER_THOUSAND = 1000
const PERCENT_SCALE = 100

const PERCENT: Intl.NumberFormatOptions = { style: 'percent' }
// A change that rounds to zero carries no sign, so "+0.00%" never suggests a direction.
const SIGNED: Intl.NumberFormatOptions = { signDisplay: 'exceptZero' }

// Shown wherever a value is missing, so every page marks gaps the same way.
export const EMPTY_VALUE = '—'

type DateInput = string | number | Date

// Building an Intl formatter costs far more than formatting with one, and a table formats every
// cell, so each (locale, options) pair is built once. Options are keyed by content because most
// call sites spread a fresh object on every call.
const dateTimeFormats = new Map<string, Intl.DateTimeFormat>()
const numberFormats = new Map<string, Intl.NumberFormat>()

function reuse<T>(cache: Map<string, T>, locale: Locale, options: object, build: () => T): T {
  const key = `${locale}|${JSON.stringify(options, Object.keys(options).sort())}`
  let formatter = cache.get(key)
  if (formatter === undefined) {
    formatter = build()
    cache.set(key, formatter)
  }
  return formatter
}

function formatDate(value: DateInput, locale: Locale, options: Intl.DateTimeFormatOptions): string {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return String(value)
  return reuse(dateTimeFormats, locale, options, () => new Intl.DateTimeFormat(locale, options)).format(date)
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
  return formatWith(value, locale, { maximumFractionDigits: MAX_MEASUREMENT_FRACTION_DIGITS })
}

// Shows exactly `fractionDigits` decimals so values in one column or axis line up.
export function formatDecimal(value: number, locale: Locale, fractionDigits: number): string {
  return formatWith(value, locale, fixedDigits(fractionDigits))
}

export function formatLoadMW(value: number, locale: Locale): string {
  return formatDecimal(value, locale, LOAD_MW_FRACTION_DIGITS)
}

export function formatLoadDelta(value: number, locale: Locale): string {
  return formatWith(value, locale, { ...fixedDigits(LOAD_MW_FRACTION_DIGITS), ...SIGNED })
}

export function formatLoadThousands(value: number, locale: Locale): string {
  return `${formatDecimal(value / MW_PER_THOUSAND, locale, LOAD_MW_FRACTION_DIGITS)}k`
}

export function formatTemperature(value: number, locale: Locale): string {
  return `${formatDecimal(value, locale, TEMPERATURE_FRACTION_DIGITS)}°C`
}

export function formatHumidity(value: number, locale: Locale): string {
  return formatPercent(value, locale, HUMIDITY_FRACTION_DIGITS)
}

// `value` is in percentage points (12.5 means 12.5%), matching how the API and demo data store rates.
export function formatPercent(value: number, locale: Locale, fractionDigits: number): string {
  return formatWith(value / PERCENT_SCALE, locale, { ...fixedDigits(fractionDigits), ...PERCENT })
}

export function formatPercentDelta(value: number, locale: Locale, fractionDigits: number): string {
  return formatWith(value / PERCENT_SCALE, locale, { ...fixedDigits(fractionDigits), ...PERCENT, ...SIGNED })
}

function fixedDigits(fractionDigits: number): Intl.NumberFormatOptions {
  return { minimumFractionDigits: fractionDigits, maximumFractionDigits: fractionDigits }
}

function formatWith(value: number, locale: Locale, options: Intl.NumberFormatOptions): string {
  return reuse(numberFormats, locale, options, () => new Intl.NumberFormat(locale, options)).format(value)
}
