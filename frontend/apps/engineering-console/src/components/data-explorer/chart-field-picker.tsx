import { type RefObject, useEffect, useId, useRef, useState } from 'react'
import { ChevronDown } from 'lucide-react'
import { useMessages } from '@/i18n/messages'
import { type ChartFieldOption, chartFieldChoices, toggleChartField } from './chart-fields'
import { explorerFieldLabel } from './field-format'

interface ChartFieldPickerProps {
  options: readonly ChartFieldOption[]
  selected: readonly string[]
  onChange: (fields: string[]) => void
}

export function ChartFieldPicker({ options, selected, onChange }: ChartFieldPickerProps) {
  const m = useMessages()
  const text = m.explorer.chart
  const [open, setOpen] = useState(false)
  const container = useRef<HTMLSpanElement>(null)
  const panelId = useId()
  useDismiss(open, container, () => setOpen(false))

  return (
    <span ref={container} className="relative">
      <button
        type="button"
        aria-expanded={open}
        aria-controls={panelId}
        onClick={() => setOpen((value) => !value)}
        className="flex items-center gap-1 rounded-lg border border-slate-800 bg-slate-900 px-2 py-1 text-slate-200"
      >
        {text.fieldPicker}
        <span aria-hidden="true" className="rounded bg-slate-800 px-1 tabular-nums text-slate-400">
          {selected.length}
        </span>
        <ChevronDown aria-hidden="true" className="h-3 w-3" />
      </button>
      {open && (
        <div
          id={panelId}
          role="group"
          aria-label={text.fieldPicker}
          className="absolute right-0 z-20 mt-1 w-72 rounded-lg border border-slate-700 bg-slate-900 p-3 shadow-xl"
        >
          <p className="mb-2 text-slate-400">{text.fieldUnitLimit}</p>
          {chartFieldChoices(options, selected).map((choice) => (
            <label
              key={choice.field}
              className={`flex items-center gap-2 py-1 ${choice.disabled ? 'text-slate-500' : 'text-slate-200'}`}
            >
              <input
                type="checkbox"
                checked={choice.checked}
                disabled={choice.disabled}
                onChange={() => onChange(toggleChartField(selected, choice.field))}
                className="accent-cyan-400"
              />
              {explorerFieldLabel(choice.field, m)}
            </label>
          ))}
        </div>
      )}
    </span>
  )
}

// The panel closes on Escape or a press outside it, like a native select.
function useDismiss(open: boolean, container: RefObject<HTMLElement | null>, close: () => void) {
  useEffect(() => {
    if (!open) return
    const onPointerDown = (event: MouseEvent) => {
      if (!container.current?.contains(event.target as Node)) close()
    }
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') close()
    }
    document.addEventListener('mousedown', onPointerDown)
    document.addEventListener('keydown', onKeyDown)
    return () => {
      document.removeEventListener('mousedown', onPointerDown)
      document.removeEventListener('keydown', onKeyDown)
    }
  }, [open, container, close])
}
