import { useState } from 'react'
import { PredictionItem } from '@/schemas/api'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { formatDateTime, formatHumidity, formatLoadMW, formatTemperature } from '@/i18n/format'
import { useLocale } from '@/i18n/locale-store'
import { useMessages } from '@/i18n/use-messages'
import { Download, FileSpreadsheet } from 'lucide-react'

interface PredictionTableProps {
  predictions?: PredictionItem[]
  isLoading: boolean
  subject?: string
}

export function PredictionTable({
  predictions,
  isLoading,
  subject = 'nationwide',
}: PredictionTableProps) {
  const [page, setPage] = useState(0)
  const m = useMessages()
  const locale = useLocale()
  const tableText = m.dashboard.table
  const pageSize = 10

  const handleExportCSV = () => {
    if (!predictions || predictions.length === 0) return

    const headers = ['Datetime', 'Predicted Load (MW)', 'Temperature (C)', 'Relative Humidity (%)']
    const rows = predictions.map((p) => [
      p.datetime,
      p.predicted_load_mw.toFixed(2),
      p.temperature.toFixed(2),
      p.relative_humidity.toFixed(2),
    ])

    const csvContent = [headers.join(','), ...rows.map((r) => r.join(','))].join('\n')
    const blob = new Blob([csvContent], { type: 'text/csv;charset=utf-8;' })
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.setAttribute('href', url)
    link.setAttribute('download', `load_forecast_${subject}_${new Date().toISOString().slice(0, 10)}.csv`)
    document.body.appendChild(link)
    link.click()
    document.body.removeChild(link)
  }

  if (isLoading || !predictions) {
    return (
      <Card className="border-slate-800 bg-slate-900/60">
        <CardHeader>
          <CardTitle className="text-base font-semibold text-slate-200">
            {tableText.loadingTitle}
          </CardTitle>
        </CardHeader>
        <CardContent className="h-48 flex items-center justify-center text-xs text-slate-500">
          {tableText.loading}
        </CardContent>
      </Card>
    )
  }

  const totalPages = Math.ceil(predictions.length / pageSize)
  const paginatedItems = predictions.slice(page * pageSize, (page + 1) * pageSize)

  return (
    <Card className="border-slate-800 bg-slate-900/60 backdrop-blur-md">
      <CardHeader className="flex flex-row items-center justify-between pb-3">
        <div className="flex items-center gap-2">
          <FileSpreadsheet className="h-4 w-4 text-cyan-400" />
          <CardTitle className="text-base font-semibold text-slate-200">
            {tableText.title(predictions.length)}
          </CardTitle>
        </div>
        <Button
          variant="outline"
          size="sm"
          onClick={handleExportCSV}
          className="gap-1.5 text-xs h-8 border-slate-700 bg-slate-900/80 hover:bg-slate-800"
        >
          <Download className="h-3.5 w-3.5" />
          {m.common.exportCsv}
        </Button>
      </CardHeader>
      <CardContent>
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>{tableText.timestamp}</TableHead>
              <TableHead className="text-right">{tableText.load}</TableHead>
              <TableHead className="text-right">{tableText.temperature}</TableHead>
              <TableHead className="text-right">{tableText.humidity}</TableHead>
              <TableHead className="text-center">{tableText.status}</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {paginatedItems.map((item, idx) => (
              <TableRow key={idx}>
                <TableCell className="font-mono text-xs text-slate-300">
                  {formatDateTime(item.datetime, locale)}
                </TableCell>
                <TableCell className="text-right font-mono font-bold text-cyan-300 text-xs">
                  {formatLoadMW(item.predicted_load_mw, locale)}
                </TableCell>
                <TableCell className="text-right font-mono text-amber-300 text-xs">
                  {formatTemperature(item.temperature, locale)}
                </TableCell>
                <TableCell className="text-right font-mono text-slate-300 text-xs">
                  {formatHumidity(item.relative_humidity, locale)}
                </TableCell>
                <TableCell className="text-center">
                  <span className="inline-block px-2 py-0.5 text-[10px] font-semibold rounded bg-cyan-500/10 text-cyan-400 border border-cyan-500/20">
                    {tableText.inferred}
                  </span>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>

        {/* Pagination Controls */}
        <div className="flex items-center justify-between pt-4 text-xs text-slate-400 border-t border-slate-800/80 mt-2">
          <span>
            {tableText.range(page * pageSize + 1, Math.min((page + 1) * pageSize, predictions.length), predictions.length)}
          </span>
          <div className="flex items-center gap-2">
            <Button
              variant="outline"
              size="sm"
              onClick={() => setPage((p) => Math.max(0, p - 1))}
              disabled={page === 0}
              className="h-7 text-xs px-2.5"
            >
              {m.common.previousPage}
            </Button>
            <span className="font-mono">
              {page + 1} / {totalPages}
            </span>
            <Button
              variant="outline"
              size="sm"
              onClick={() => setPage((p) => Math.min(totalPages - 1, p + 1))}
              disabled={page >= totalPages - 1}
              className="h-7 text-xs px-2.5"
            >
              {m.common.nextPage}
            </Button>
          </div>
        </div>
      </CardContent>
    </Card>
  )
}
