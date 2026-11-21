import { useState } from 'react'
import type { ForecastStep } from '@/schemas/published'
import { Button } from '@shiro-mlops/shared/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@shiro-mlops/shared/ui/card'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@shiro-mlops/shared/ui/table'
import { formatDateTime, formatLoadMW } from '@shiro-mlops/shared/i18n/format'
import { useLocale } from '@shiro-mlops/shared/i18n/locale-store'
import { useMessages } from '@/i18n/messages'
import { Download, FileSpreadsheet } from 'lucide-react'

interface PredictionTableProps {
  steps?: ForecastStep[]
  isLoading: boolean
  issuedAt: string | null
}

export function PredictionTable({ steps, isLoading, issuedAt }: PredictionTableProps) {
  const [page, setPage] = useState(0)
  const m = useMessages()
  const locale = useLocale()
  const tableText = m.dashboard.table
  const pageSize = 10

  const handleExportCSV = () => {
    if (!steps || steps.length === 0 || issuedAt === null) return

    // Values stay as published: target hours keep their +08:00 offset, whatever the interface locale.
    const headers = ['Target Hour', 'Predicted Load (MW)']
    const rows = steps.map((step) => [step.target_hour, step.predicted_load_mw.toFixed(2)])

    const csvContent = [headers.join(','), ...rows.map((r) => r.join(','))].join('\n')
    const blob = new Blob([csvContent], { type: 'text/csv;charset=utf-8;' })
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.setAttribute('href', url)
    // Named after the forecast's Taipei issue date (the offset-carrying string's own date), not the viewer's clock.
    link.setAttribute('download', `issued_forecast_${issuedAt.slice(0, 10)}.csv`)
    document.body.appendChild(link)
    link.click()
    document.body.removeChild(link)
  }

  if (isLoading || !steps) {
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

  const totalPages = Math.ceil(steps.length / pageSize)
  const paginatedItems = steps.slice(page * pageSize, (page + 1) * pageSize)

  return (
    <Card className="border-slate-800 bg-slate-900/60 backdrop-blur-md">
      <CardHeader className="flex flex-row items-center justify-between pb-3">
        <div className="flex items-center gap-2">
          <FileSpreadsheet className="h-4 w-4 text-cyan-400" />
          <CardTitle className="text-base font-semibold text-slate-200">
            {tableText.title(steps.length)}
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
              <TableHead>{tableText.targetHour}</TableHead>
              <TableHead className="text-right">{tableText.load}</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {paginatedItems.map((item) => (
              <TableRow key={item.target_hour}>
                <TableCell className="font-mono text-xs text-slate-300">
                  {formatDateTime(item.target_hour, locale)}
                </TableCell>
                <TableCell className="text-right font-mono font-bold text-cyan-300 text-xs">
                  {formatLoadMW(item.predicted_load_mw, locale)}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>

        {/* Pagination Controls */}
        <div className="flex items-center justify-between pt-4 text-xs text-slate-400 border-t border-slate-800/80 mt-2">
          <span>
            {tableText.range(page * pageSize + 1, Math.min((page + 1) * pageSize, steps.length), steps.length)}
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
