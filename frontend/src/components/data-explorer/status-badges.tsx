import { Badge } from '@/components/ui/badge'
import { DatasetStatus } from '@/schemas/data-explorer'

const overallVariant = {
  healthy: 'success',
  warning: 'warning',
  critical: 'destructive',
  unknown: 'secondary',
} as const

export function StatusBadges({ status }: { status: DatasetStatus }) {
  return (
    <div className="flex flex-wrap gap-2">
      <Badge variant={overallVariant[status.overall]}>{status.overall}</Badge>
      <Badge variant="outline">availability: {status.availability}</Badge>
      <Badge variant="outline">freshness: {status.freshness}</Badge>
      <Badge variant="outline">completeness: {status.completeness}</Badge>
    </div>
  )
}
