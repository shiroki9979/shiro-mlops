import { useState } from 'react'
import type { BucketSelection } from '@/lib/explorer-window'

// What recharts passes to chart-level mouse handlers; null when the pointer is outside the plot.
type ChartPointerState = { activeLabel?: unknown } | null

export interface ChartBrushHandlers {
  onMouseDown: (state: ChartPointerState) => void
  onMouseMove: (state: ChartPointerState) => void
  onMouseUp: (state: ChartPointerState) => void
  onMouseLeave: () => void
}

// Renderers spread `handlers` onto their recharts chart and draw `selection` as a ReferenceArea,
// so every chart type shares one drag-to-window behaviour.
export interface ChartBrush {
  handlers: ChartBrushHandlers
  selection: BucketSelection | null
}

// A press and release on the same bucket is a click, which only shows the tooltip.
export function useChartBrush(onSelect: (selection: BucketSelection) => void): ChartBrush {
  const [selection, setSelection] = useState<BucketSelection | null>(null)
  const extendTo = (state: ChartPointerState): BucketSelection | null => {
    const instant = bucketInstant(state)
    return selection && instant !== undefined ? { ...selection, to: instant } : selection
  }

  return {
    selection,
    handlers: {
      onMouseDown: (state) => {
        const instant = bucketInstant(state)
        setSelection(instant === undefined ? null : { from: instant, to: instant })
      },
      onMouseMove: (state) => {
        if (selection) setSelection(extendTo(state))
      },
      onMouseUp: (state) => {
        const finished = extendTo(state)
        setSelection(null)
        if (finished && finished.from !== finished.to) onSelect(finished)
      },
      onMouseLeave: () => setSelection(null),
    },
  }
}

function bucketInstant(state: ChartPointerState): number | undefined {
  return typeof state?.activeLabel === 'number' ? state.activeLabel : undefined
}
