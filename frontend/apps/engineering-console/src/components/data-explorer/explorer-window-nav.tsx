import { Button } from '@shiro-mlops/shared/ui/button'
import { ChevronLeft, ChevronRight } from 'lucide-react'
import { type Messages, useMessages } from '@/i18n/messages'
import {
  type ExplorerWindow,
  type QuickRangeId,
  quickRangeWindow,
  type ShiftDirection,
  shiftWindow,
} from '@/lib/explorer-window'
import type { ExplorerDatasetConfig } from './catalog'

interface ExplorerWindowNavProps {
  dataset: ExplorerDatasetConfig
  window: ExplorerWindow
  onWindowChange: (window: ExplorerWindow) => void
}

export function ExplorerWindowNav({ dataset, window, onWindowChange }: ExplorerWindowNavProps) {
  const filtersText = useMessages().explorer.filters
  const shiftTo = (direction: ShiftDirection) => {
    const shifted = shiftWindow(window, direction)
    if (shifted) onWindowChange(shifted)
  }
  const canShift = shiftWindow(window, 'earlier') !== null

  return (
    <div className="flex flex-wrap items-center gap-2">
      <span className="text-xs text-slate-400">{filtersText.quickRangesLabel}</span>
      {dataset.quickRanges.map((range) => (
        <Button
          key={range}
          variant="outline"
          size="sm"
          className="h-8 px-3 text-xs"
          onClick={() => onWindowChange(quickRangeWindow(range, new Date(), dataset.maxDays))}
        >
          {quickRangeLabel(range, filtersText, dataset.maxDays)}
        </Button>
      ))}
      <div className="ml-auto flex gap-1">
        <Button
          variant="outline"
          size="sm"
          className="h-8 px-2"
          aria-label={filtersText.shiftEarlier}
          title={filtersText.shiftEarlier}
          disabled={!canShift}
          onClick={() => shiftTo('earlier')}
        >
          <ChevronLeft className="h-4 w-4" />
        </Button>
        <Button
          variant="outline"
          size="sm"
          className="h-8 px-2"
          aria-label={filtersText.shiftLater}
          title={filtersText.shiftLater}
          disabled={!canShift}
          onClick={() => shiftTo('later')}
        >
          <ChevronRight className="h-4 w-4" />
        </Button>
      </div>
    </div>
  )
}

function quickRangeLabel(
  range: QuickRangeId,
  filtersText: Messages['explorer']['filters'],
  detailLimitDays: number,
): string {
  return range === 'detailLimit'
    ? filtersText.quickRanges.detailLimit(String(detailLimitDays))
    : filtersText.quickRanges[range]
}
