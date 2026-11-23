import { Badge } from '@shiro-mlops/shared/ui/badge'
import { useMessages } from '@/i18n/messages'
import { DatasetStatus } from '@/schemas/data-explorer'

// Variants key off the raw API enum; only the visible text is translated.
const overallVariant = {
  healthy: 'success',
  warning: 'warning',
} as const

export function StatusBadges({ status }: { status: DatasetStatus }) {
  const m = useMessages()
  const labeled = m.common.labeled
  return (
    <div className="flex flex-wrap gap-2">
      <Badge variant={overallVariant[status.overall]}>{m.status.overall[status.overall]}</Badge>
      {status.kind === 'empty' ? (
        <Badge variant="outline">{m.status.empty}</Badge>
      ) : (
        <>
          <Badge variant="outline">{labeled(m.status.freshnessLabel, m.status.freshness[status.freshness])}</Badge>
          <Badge variant="outline">
            {labeled(m.status.completenessLabel, m.status.completeness[status.completeness])}
          </Badge>
        </>
      )}
    </div>
  )
}
