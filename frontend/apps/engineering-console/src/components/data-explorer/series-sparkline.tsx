import { Line, LineChart, ResponsiveContainer, XAxis, YAxis } from 'recharts'
import type { ExplorerWindow } from '@/lib/explorer-window'
import { type PlottedSeries, toChartRows } from './chart-series'

const STROKE_WIDTH = 1.25

interface SeriesSparklineProps {
  series: PlottedSeries[]
  // The axis spans the whole requested window, so data that stopped arriving shows as an empty tail.
  window: ExplorerWindow
  label: string
}

// No axes, tooltip or legend: the card only shows whether the line is there, flat, or broken.
// Gap-filled `null` points break the line, as on the chart card.
export function SeriesSparkline({ series, window, label }: SeriesSparklineProps) {
  const rows = toChartRows(series)
  return (
    <div role="img" aria-label={label} className="h-12 w-full">
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={rows} margin={{ top: 4, right: 2, left: 2, bottom: 4 }}>
          <XAxis dataKey="t" type="number" scale="time" domain={[Date.parse(window.start), Date.parse(window.end)]} hide />
          <YAxis domain={['auto', 'auto']} hide />
          {series.map((item) => (
            <Line
              key={item.key}
              type="linear"
              dataKey={item.key}
              stroke={item.color}
              strokeWidth={STROKE_WIDTH}
              dot={false}
              connectNulls={item.connectNulls ?? false}
              isAnimationActive={false}
            />
          ))}
        </LineChart>
      </ResponsiveContainer>
    </div>
  )
}
