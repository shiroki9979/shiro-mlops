import type { ExplorerFieldKey } from './catalog'
import { explorerFieldKind } from './field-format'

export type CellPresentation = 'number' | 'identifier' | 'time' | 'statusBadge' | 'chip' | 'text'

// Categories with few distinct values read faster as chips than as repeated words.
const CHIP_FIELDS: ReadonlySet<string> = new Set<ExplorerFieldKey>(['region', 'unit_type', 'dataset_id'])
// Codes compared character by character keep a monospace face; names and free text do not.
const IDENTIFIER_FIELDS: ReadonlySet<string> = new Set<ExplorerFieldKey>([
  'station_id',
  'geocode',
  'town_code',
  'missing_station_ids',
  'missing_station_id',
  'missing_geocodes',
  'missing_geocode',
])

const CELL_CLASS: Record<CellPresentation, string> = {
  number: 'text-right font-mono tabular-nums',
  identifier: 'font-mono',
  time: 'whitespace-nowrap tabular-nums',
  statusBadge: '',
  chip: '',
  text: '',
}

export function explorerCellPresentation(column: ExplorerFieldKey): CellPresentation {
  if (CHIP_FIELDS.has(column)) return 'chip'
  if (IDENTIFIER_FIELDS.has(column)) return 'identifier'
  const kind = explorerFieldKind(column)
  if (kind === 'measurement') return 'number'
  if (kind === 'timestamp' || kind === 'date') return 'time'
  if (kind === 'flag' || kind === 'auditStatus') return 'statusBadge'
  return 'text'
}

export function explorerCellClass(column: ExplorerFieldKey): string {
  return CELL_CLASS[explorerCellPresentation(column)]
}
