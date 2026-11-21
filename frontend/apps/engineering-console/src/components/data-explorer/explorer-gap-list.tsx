import { useId, useState } from 'react'
import { ChevronRight } from 'lucide-react'
import { formatNumber, TAIPEI_TIME_ZONE } from '@shiro-mlops/shared/i18n/format'
import type { Locale } from '@shiro-mlops/shared/i18n/locale-store'
import { useLocale } from '@shiro-mlops/shared/i18n/locale-store'
import { type Messages, useMessages } from '@/i18n/messages'
import { type GapRange, groupGapSlots } from '@/lib/explorer-gaps'
import { datasetById, type ExplorerDatasetId } from './catalog'

const STATION_GROUPED_DATASETS: ReadonlySet<ExplorerDatasetId> = new Set(['cwa_observations'])
const MINUTES_PER_HOUR = 60
const SECONDS_PER_MINUTE = 60

const GAP_DATE: Intl.DateTimeFormatOptions = { month: '2-digit', day: '2-digit', timeZone: TAIPEI_TIME_ZONE }
const GAP_TIME: Intl.DateTimeFormatOptions = {
  hour: '2-digit',
  minute: '2-digit',
  hourCycle: 'h23',
  timeZone: TAIPEI_TIME_ZONE,
}

interface ExplorerGapListProps {
  datasetId: ExplorerDatasetId
  missingSlots: string[]
}

export function ExplorerGapList({ datasetId, missingSlots }: ExplorerGapListProps) {
  const m = useMessages()
  const locale = useLocale()
  const [expanded, setExpanded] = useState(false)
  const listId = useId()
  if (missingSlots.length === 0) return null
  const cadenceMinutes = datasetById(datasetId).cadenceSeconds / SECONDS_PER_MINUTE
  const resultsText = m.explorer.results
  const groups = groupGapSlots(missingSlots, cadenceMinutes, STATION_GROUPED_DATASETS.has(datasetId))
  const describe = (range: GapRange) =>
    resultsText.gapRange(rangeLabel(range, locale), lengthLabel(range.slotCount * cadenceMinutes, locale, resultsText))
  return (
    <div className="mb-3 text-xs">
      <button
        type="button"
        className="inline-flex items-center gap-1 text-amber-300 hover:text-amber-200"
        aria-expanded={expanded}
        aria-controls={listId}
        onClick={() => setExpanded((open) => !open)}
      >
        <ChevronRight aria-hidden className={`h-3 w-3 transition-transform ${expanded ? 'rotate-90' : ''}`} />
        {resultsText.gaps(formatNumber(missingSlots.length, locale))}
      </button>
      {expanded && (
        <section
          id={listId}
          aria-label={resultsText.gapListTitle}
          className="mt-2 max-h-64 overflow-auto rounded-lg border border-slate-800 bg-slate-950/40 px-3 py-2 text-slate-300"
        >
          {groups.map((group) =>
            group.stationId === undefined ? (
              <GapRangeList key="all" ranges={group.ranges} describe={describe} />
            ) : (
              <StationGapRanges
                key={group.stationId}
                heading={resultsText.gapStation(group.stationId)}
                ranges={group.ranges}
                describe={describe}
              />
            ),
          )}
        </section>
      )}
    </div>
  )
}

interface GapRangeListProps {
  ranges: GapRange[]
  describe: (range: GapRange) => string
  labelledBy?: string
}

function GapRangeList({ ranges, describe, labelledBy }: GapRangeListProps) {
  return (
    <ul aria-labelledby={labelledBy} className="space-y-0.5 font-mono">
      {ranges.map((range) => (
        <li key={range.start}>{describe(range)}</li>
      ))}
    </ul>
  )
}

function StationGapRanges({ heading, ...listProps }: Omit<GapRangeListProps, 'labelledBy'> & { heading: string }) {
  const headingId = useId()
  return (
    <div className="mb-2 last:mb-0">
      <h4 id={headingId} className="mb-0.5 font-semibold text-slate-400">{heading}</h4>
      <GapRangeList {...listProps} labelledBy={headingId} />
    </div>
  )
}

function rangeLabel(range: GapRange, locale: Locale): string {
  const startDate = formatPart(range.start, locale, GAP_DATE)
  const start = `${startDate} ${formatPart(range.start, locale, GAP_TIME)}`
  if (range.slotCount === 1) return start
  const endDate = formatPart(range.end, locale, GAP_DATE)
  const endTime = formatPart(range.end, locale, GAP_TIME)
  return `${start}–${endDate === startDate ? endTime : `${endDate} ${endTime}`}`
}

function lengthLabel(totalMinutes: number, locale: Locale, resultsText: Messages['explorer']['results']): string {
  const hours = Math.floor(totalMinutes / MINUTES_PER_HOUR)
  const minutes = totalMinutes % MINUTES_PER_HOUR
  if (hours === 0) return resultsText.gapMinutes(formatNumber(minutes, locale))
  if (minutes === 0) return resultsText.gapHours(formatNumber(hours, locale))
  return resultsText.gapHoursMinutes(formatNumber(hours, locale), formatNumber(minutes, locale))
}

function formatPart(value: string, locale: Locale, options: Intl.DateTimeFormatOptions): string {
  return new Intl.DateTimeFormat(locale, options).format(new Date(value))
}
