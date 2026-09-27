import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { formatExplorerValue } from '@/lib/data-explorer'
import type { ListEnvelope } from '@/schemas/data-explorer'
import type { ExplorerDatasetConfig } from './catalog'

interface ExplorerResultsProps {
  dataset: ExplorerDatasetConfig
  data?: ListEnvelope
  error: unknown
  isError: boolean
  isLoading: boolean
  canRestart: boolean
  onSelect: (row: Record<string, unknown>) => void
  onNextPage: (cursor: string | undefined) => void
  onRestart: () => void
}

const CURSOR_REJECTED_STATUS = 400

function errorStatus(error: unknown): unknown {
  return typeof error === 'object' && error !== null && 'status' in error
    ? error.status
    : undefined
}

function isCursorRejected(error: unknown): boolean {
  return errorStatus(error) === CURSOR_REJECTED_STATUS
}

function listErrorMessage(error: unknown): string {
  const status = errorStatus(error)
  if (status === CURSOR_REJECTED_STATUS) return '分頁游標無效或已與目前篩選條件不相容。'
  if (status === 422) return '篩選條件無效，請確認時間範圍與欄位格式。'
  if (status === 503) return '資料庫目前無法連線，請稍後再試。'
  return '查詢失敗，請稍後再試。'
}

export function ExplorerResults({
  dataset,
  data,
  error,
  isError,
  isLoading,
  canRestart,
  onSelect,
  onNextPage,
  onRestart,
}: ExplorerResultsProps) {
  return (
    <Card>
      <CardContent className="pt-6">
        {isLoading ? (
          <p className="text-xs text-slate-500">載入資料中...</p>
        ) : isError ? (
          <div>
            <p className="text-xs text-rose-300">{listErrorMessage(error)}</p>
            {canRestart && isCursorRejected(error) && (
              <Button className="mt-4" variant="outline" onClick={onRestart}>回到第一頁</Button>
            )}
          </div>
        ) : !data || data.items.length === 0 ? (
          <p className="text-xs text-slate-500">查無符合資料，查詢成功但結果為空。</p>
        ) : (
          <>
            {data.missing_slots.length > 0 && (
              <p className="text-xs text-amber-300 mb-3">
                查詢區間缺口：{data.missing_slots.length} 筆
              </p>
            )}
            <Table>
              <TableHeader>
                <TableRow>
                  {dataset.columns.map((column) => (
                    <TableHead key={column.key}>{column.label}</TableHead>
                  ))}
                </TableRow>
              </TableHeader>
              <TableBody>
                {data.items.map((row, index) => (
                  <TableRow key={index} className="cursor-pointer" onClick={() => onSelect(row)}>
                    {dataset.columns.map((column) => (
                      <TableCell key={column.key} className="font-mono text-xs">
                        {formatExplorerValue(row[column.key])}
                      </TableCell>
                    ))}
                  </TableRow>
                ))}
              </TableBody>
            </Table>
            {data.has_more && (
              <Button
                className="mt-4"
                variant="outline"
                onClick={() => onNextPage(data.next_cursor ?? undefined)}
              >
                下一頁
              </Button>
            )}
          </>
        )}
      </CardContent>
    </Card>
  )
}
