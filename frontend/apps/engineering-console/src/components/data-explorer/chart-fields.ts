import type { ExplorerFieldKey } from './catalog'

// A chart draws at most two units: the first selected unit takes the left axis, the second the right.
export const MAX_CHART_UNITS = 2

export interface ChartFieldOption {
  field: ExplorerFieldKey
  // SYNC(src/shiro_mlops/service/data_explorer/datasets/power.py, src/shiro_mlops/service/data_explorer/datasets/weather.py, src/shiro_mlops/service/data_explorer/datasets/audits.py): the `SeriesField.unit` each dataset's SeriesOptions declares, known before any response so a third unit can be disabled up front.
  unit: string
}

export interface ChartFieldChoice extends ChartFieldOption {
  checked: boolean
  disabled: boolean
}

// The last selected field cannot be cleared, and a field of a third unit cannot be added.
export function chartFieldChoices(options: readonly ChartFieldOption[], selected: readonly string[]): ChartFieldChoice[] {
  const units = selectedUnits(options, selected)
  return options.map((option) => {
    const checked = selected.includes(option.field)
    const disabled = checked
      ? selected.length === 1
      : units.length >= MAX_CHART_UNITS && !units.includes(option.unit)
    return { ...option, checked, disabled }
  })
}

// Added fields go last, so the unit order (and with it the axis side) follows the selection order.
export function toggleChartField<T extends string>(selected: readonly T[], field: T): T[] {
  return selected.includes(field) ? selected.filter((item) => item !== field) : [...selected, field]
}

function selectedUnits(options: readonly ChartFieldOption[], selected: readonly string[]): string[] {
  const unitOf = new Map(options.map((option) => [option.field as string, option.unit]))
  return [...new Set(selected.flatMap((field) => unitOf.get(field) ?? []))]
}
