import { Badge } from '@/components/ui/badge'
import { useMessages } from '@/i18n/use-messages'
import { DatasetStatus } from '@/schemas/data-explorer'
import { translateCompleteness } from './status-text'

// Variants key off the raw API enum; only the visible text is translated.
const overallVariant = {
  healthy: 'success',
  warning: 'warning',
  critical: 'destructive',
  unknown: 'secondary',
} as const

export function StatusBadges({ status }: { status: DatasetStatus }) {
  const m = useMessages()
  const labeled = m.common.labeled
  return (
    <div className="flex flex-wrap gap-2">
      <Badge variant={overallVariant[status.overall]}>{m.status.overall[status.overall]}</Badge>
      <Badge variant="outline">
        {labeled(m.status.availabilityLabel, m.status.availability[status.availability])}
      </Badge>
      <Badge variant="outline">{labeled(m.status.freshnessLabel, m.status.freshness[status.freshness])}</Badge>
      <Badge variant="outline">
        {labeled(m.status.completenessLabel, translateCompleteness(status.completeness, m))}
      </Badge>
    </div>
  )
}
