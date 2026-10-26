import { formatNumber, formatTimestamp } from '@/i18n/format'
import type { Locale } from '@/i18n/locale-store'
import type { Messages } from '@/i18n/use-messages'
import type { DatasetStatus } from '@/schemas/data-explorer'
import { isExplorerDatasetId } from './catalog'

const EMPTY_VALUE = '—'

// The API also returns a Chinese label; the dictionary entry wins so the name follows the UI language.
export function datasetLabel(status: Pick<DatasetStatus, 'id' | 'label'>, messages: Messages): string {
  return isExplorerDatasetId(status.id) ? messages.explorer.datasets[status.id].label : status.label
}

export function optionalTimestamp(value: string | null | undefined, locale: Locale): string {
  return value ? formatTimestamp(value, locale) : EMPTY_VALUE
}

export function optionalSeconds(value: number | null | undefined, locale: Locale): string {
  return value == null ? EMPTY_VALUE : formatNumber(value, locale)
}
