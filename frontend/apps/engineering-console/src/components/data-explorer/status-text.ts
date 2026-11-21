import { EMPTY_VALUE, formatNumber, formatTimestamp } from '@shiro-mlops/shared/i18n/format'
import type { Locale } from '@shiro-mlops/shared/i18n/locale-store'
import type { Messages } from '@/i18n/messages'
import type { DatasetStatus } from '@/schemas/data-explorer'
import { isExplorerDatasetId } from './catalog'

// The API also returns a Chinese label; the dictionary entry wins so the name follows the UI language.
export function datasetLabel(status: Pick<DatasetStatus, 'id' | 'label'>, m: Messages): string {
  return isExplorerDatasetId(status.id) ? m.explorer.datasets[status.id].label : status.label
}

// Takes a plain string because audit rows carry the same enum untyped; unknown values stay verbatim.
export function translateCompleteness(value: string, m: Messages): string {
  const labels: Record<string, string> = m.status.completeness
  return labels[value] ?? value
}

export function optionalTimestamp(value: string | null | undefined, locale: Locale): string {
  return value ? formatTimestamp(value, locale) : EMPTY_VALUE
}

export function optionalSeconds(value: number | null | undefined, locale: Locale): string {
  return value == null ? EMPTY_VALUE : formatNumber(value, locale)
}
