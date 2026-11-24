// The columns are the first row's keys, so every row carries the same keys. Every cell is quoted, so
// a comma, quote or line break in a value never shifts a column.
export function exportCsv(filename: string, rows: Array<Record<string, unknown>>): void {
  if (rows.length === 0) return
  const headers = Object.keys(rows[0])
  const csv = [
    headers.map(csvCell).join(','),
    ...rows.map((row) => headers.map((header) => csvCell(row[header])).join(',')),
  ].join('\r\n')
  if (typeof URL.createObjectURL !== 'function') return
  const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' })
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  document.body.appendChild(link)
  link.click()
  document.body.removeChild(link)
  URL.revokeObjectURL(url)
}

function csvCell(value: unknown): string {
  const text = value !== null && typeof value === 'object' ? JSON.stringify(value) : String(value ?? '')
  return `"${text.replaceAll('"', '""')}"`
}
