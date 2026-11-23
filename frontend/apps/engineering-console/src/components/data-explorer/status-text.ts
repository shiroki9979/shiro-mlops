import type { Messages } from '@/i18n/messages'
import type { DatasetStatus } from '@/schemas/data-explorer'
import { isExplorerDatasetId } from './catalog'

// The API also returns a Chinese label; the dictionary entry wins so the name follows the UI language.
export function datasetLabel(status: Pick<DatasetStatus, 'id' | 'label'>, m: Messages): string {
  return isExplorerDatasetId(status.id) ? m.explorer.datasets[status.id].label : status.label
}

// For audit rows, which carry the completeness enum untyped; unknown values stay verbatim.
export function translateCompleteness(value: string, m: Messages): string {
  const labels: Record<string, string> = m.status.completeness
  return labels[value] ?? value
}

// Enum value sets whose display text comes from the dictionary; other values are shown verbatim.
export type ExplorerValueLabels = 'completeness'
export const EXPLORER_VALUE_LABELS: Record<ExplorerValueLabels, (value: string, m: Messages) => string> = {
  completeness: translateCompleteness,
}

const completenessVariant: Record<string, 'success' | 'warning'> = {
  complete: 'success',
  incomplete: 'warning',
}

// Incomplete data lowers a dataset's overall status to warning, so its badge shares that colour.
export function completenessBadgeVariant(value: string): 'success' | 'warning' | 'secondary' {
  return completenessVariant[value] ?? 'secondary'
}
