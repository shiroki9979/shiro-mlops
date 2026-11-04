import { Button } from '@/components/ui/button'
import { useLocale } from '@/i18n/locale-store'
import { useMessages } from '@/i18n/use-messages'
import { explorerFieldLabel, formatExplorerField } from './field-format'

interface ExplorerDetailProps {
  selected: Record<string, unknown> | null
  onClose: () => void
}

export function ExplorerDetail({ selected, onClose }: ExplorerDetailProps) {
  const m = useMessages()
  const locale = useLocale()
  if (!selected) return null

  return (
    <div className="fixed inset-y-0 right-0 w-full max-w-md border-l border-slate-800 bg-slate-950 p-6 overflow-y-auto z-50">
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-sm font-semibold text-slate-100">{m.explorer.detail.title}</h2>
        <Button variant="ghost" size="sm" onClick={onClose}>
          {m.common.close}
        </Button>
      </div>
      <dl className="space-y-2 text-xs">
        {Object.entries(selected).map(([key, value]) => (
          <div key={key}>
            <dt className="text-slate-500">{explorerFieldLabel(key, m)}</dt>
            <dd className="font-mono text-slate-200">{formatExplorerField(key, value, { locale, m })}</dd>
          </div>
        ))}
      </dl>
    </div>
  )
}
