import { useId } from 'react'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@shiro-mlops/shared/ui/select'
import { Switch } from '@shiro-mlops/shared/ui/switch'
import { useMessages } from '@/i18n/messages'
import type { ExplorerFilterField as FilterField } from './catalog'
import { explorerFieldLabel } from './field-format'
import { translateCompleteness } from './status-text'

// Radix forbids an empty item value, so "no filter" needs a sentinel that never reaches the URL.
const NO_FILTER = '__no_filter__'
// SYNC(src/shiro_mlops/service/data_explorer/values.py): is_truthy.
const TRUTHY_VALUES = new Set(['1', 'true', 'yes'])

interface ExplorerFilterFieldProps {
  field: FilterField
  value: string
  onChange: (value: string) => void
}

export function ExplorerFilterField({ field, value, onChange }: ExplorerFilterFieldProps) {
  const m = useMessages()
  const labelId = useId()
  const label = explorerFieldLabel(field.key, m)
  const control = field.control

  if (control?.kind === 'switch') {
    return (
      <div className="text-xs text-slate-400 space-y-1">
        <span id={labelId}>{label}</span>
        <div className="flex h-[42px] items-center">
          <Switch
            aria-labelledby={labelId}
            checked={TRUTHY_VALUES.has(value.toLowerCase())}
            onCheckedChange={(checked) => onChange(checked ? 'true' : '')}
          />
        </div>
      </div>
    )
  }

  if (control?.kind === 'select') {
    return (
      <div className="text-xs text-slate-400 space-y-1">
        <span id={labelId}>{label}</span>
        <Select value={value || NO_FILTER} onValueChange={(next) => onChange(next === NO_FILTER ? '' : next)}>
          <SelectTrigger aria-labelledby={labelId} className="h-[42px]">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={NO_FILTER}>{m.explorer.filters.noFilter}</SelectItem>
            {control.options.map((option) => (
              <SelectItem key={option} value={option}>
                {translateCompleteness(option, m)}
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
        value={value}
        onChange={(event) => onChange(event.target.value)}
      />
    </label>
  )
}
