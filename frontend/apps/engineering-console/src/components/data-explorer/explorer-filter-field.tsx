import { useId } from 'react'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@shiro-mlops/shared/ui/select'
import { Switch } from '@shiro-mlops/shared/ui/switch'
import { useMessages } from '@/i18n/messages'
import type { ExplorerFilterField as FilterField } from './catalog'
import type { ExplorerFilterValue } from './explorer-query-state'
import { explorerFieldLabel } from './field-format'
import { EXPLORER_VALUE_LABELS } from './status-text'

// Radix forbids an empty item value, so "no filter" needs a sentinel that never reaches the URL.
const NO_FILTER = '__no_filter__'

interface ExplorerFilterFieldProps {
  field: FilterField
  value: ExplorerFilterValue | undefined
  // `undefined` clears the filter, whichever control it comes from.
  onChange: (value: ExplorerFilterValue | undefined) => void
}

export function ExplorerFilterField({ field, value, onChange }: ExplorerFilterFieldProps) {
  const m = useMessages()
  const labelId = useId()
  const label = explorerFieldLabel(field.key, m)
  const control = field.control
  const text = typeof value === 'string' ? value : ''

  if (control?.kind === 'switch') {
    return (
      <div className="text-xs text-slate-400 space-y-1">
        <span id={labelId}>{label}</span>
        <div className="flex h-[34px] items-center">
          <Switch
            aria-labelledby={labelId}
            checked={value === true}
            onCheckedChange={(checked) => onChange(checked || undefined)}
          />
        </div>
      </div>
    )
  }

  if (control?.kind === 'select') {
    const optionLabel = control.optionLabels ? EXPLORER_VALUE_LABELS[control.optionLabels] : undefined
    return (
      <div className="text-xs text-slate-400 space-y-1">
        <span id={labelId}>{label}</span>
        <Select value={text || NO_FILTER} onValueChange={(next) => onChange(next === NO_FILTER ? undefined : next)}>
          <SelectTrigger aria-labelledby={labelId} className="h-auto py-2 text-xs">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={NO_FILTER}>{m.explorer.filters.noFilter}</SelectItem>
            {control.options.map((option) => (
              <SelectItem key={option} value={option}>
                {optionLabel ? optionLabel(option, m) : option}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>
    )
  }

  return (
    <label className="text-xs text-slate-400 space-y-1">
      <span>{label}</span>
      <input
        className="w-full rounded-lg border border-slate-800 bg-slate-900 px-3 py-2 text-slate-200"
        placeholder={field.placeholder}
        value={text}
        onChange={(event) => onChange(event.target.value || undefined)}
      />
    </label>
  )
}
