import { Badge } from '@shiro-mlops/shared/ui/badge'
import type { ExplorerFieldKey } from './catalog'
import { explorerCellPresentation } from './cell-presentation'
import { completenessBadgeVariant } from './status-text'

const COMPACT_BADGE = 'py-0 px-2 whitespace-nowrap'

interface ExplorerCellValueProps {
  column: ExplorerFieldKey
  value: unknown
  text: string
}

// `text` is the formatted value; badges and chips only restyle it so the detail drawer and tests read the same words.
export function ExplorerCellValue({ column, value, text }: ExplorerCellValueProps) {
  if (value === null || value === undefined || value === '') return <>{text}</>
  const presentation = explorerCellPresentation(column)
  if (presentation === 'statusBadge') {
    return <Badge variant={completenessBadgeVariant(statusValue(value))} className={COMPACT_BADGE}>{text}</Badge>
  }
  if (presentation === 'chip') {
    return <Badge variant="secondary" className={`${COMPACT_BADGE} rounded-md font-medium`}>{text}</Badge>
  }
  return <>{text}</>
}

// slot_complete is a boolean flag; audit status is already the completeness enum.
function statusValue(value: unknown): string {
  if (typeof value === 'boolean') return value ? 'complete' : 'incomplete'
  return String(value)
}
