import { formatDateTime } from '@shiro-mlops/shared/i18n/format'
import type { Locale } from '@shiro-mlops/shared/i18n/locale-store'
import type { Messages } from '@/i18n/messages'
import { CATEGORY_PALETTES, FORECAST_VINTAGE_COLORS, categoryColor } from '@/lib/chart-palette'
import type { Series } from '@/schemas/data-explorer'
import { type ExplorerChartConfig, POWER_UNIT } from './catalog'
import type { PlottedSeries } from './chart-series'
import { explorerFieldLabel } from './field-format'
import { translateCompleteness } from './status-text'

// SYNC(src/shiro_mlops/service/data_explorer/values.py): WAN_KW_TO_MW.
const MW_PER_WAN_KW = 10

const GROUP_LABELS: Record<NonNullable<ExplorerChartConfig['groupLabels']>, (value: string, m: Messages) => string> = {
  completeness: translateCompleteness,
}

// Names and colours each series the same way on the chart card and the home sparklines.
export function plotSeries(series: Series[], chart: ExplorerChartConfig, m: Messages, locale: Locale): PlottedSeries[] {
  return groupedSeries(series, chart, m, locale).map((item) => ({ ...item, connectNulls: chart.sparsePoints }))
}

function groupedSeries(series: Series[], chart: ExplorerChartConfig, m: Messages, locale: Locale): PlottedSeries[] {
  const vintageGroup = chart.vintageGroup
  if (vintageGroup && series.some((item) => item.group[vintageGroup])) return plotVintages(series, vintageGroup, m, locale)
  const multipleFields = new Set(series.map((item) => item.field)).size > 1
  const palette = chart.colorBy ? CATEGORY_PALETTES[chart.colorBy.palette] : undefined
  return series.map((item, index) => ({
    key: `s${index}`,
    field: item.field,
    name: seriesName(item, multipleFields, chart, m),
    color: categoryColor(palette, chart.colorBy ? item.group[chart.colorBy.group] : undefined, index),
    unit: item.unit,
    points: item.points,
    tooltipAlternate:
      chart.tooltipWanKw && item.unit === POWER_UNIT
        ? { divisor: MW_PER_WAN_KW, format: m.explorer.chart.wanKw }
        : undefined,
  }))
}

// Newest issue first and brightest; vintages past the ramp share its darkest step. Other group
// values are named only where they tell series apart (e.g. two datasets for one issue time).
function plotVintages(series: Series[], vintageGroup: string, m: Messages, locale: Locale): PlottedSeries[] {
  const issues = [...new Set(series.map((item) => item.group[vintageGroup]))].sort().reverse()
  const multipleFields = new Set(series.map((item) => item.field)).size > 1
  const varyingKeys = Object.keys(series[0].group).filter(
    (key) => key !== vintageGroup && new Set(series.map((item) => item.group[key])).size > 1,
  )
  const ordered = [...series].sort((a, b) => issues.indexOf(a.group[vintageGroup]) - issues.indexOf(b.group[vintageGroup]))
  return ordered.map((item, index) => {
    const rank = Math.min(issues.indexOf(item.group[vintageGroup]), FORECAST_VINTAGE_COLORS.length - 1)
    const vintage = [formatDateTime(item.group[vintageGroup], locale), ...varyingKeys.map((key) => item.group[key])].join(' · ')
    return {
      key: `s${index}`,
      field: item.field,
      name: multipleFields ? `${explorerFieldLabel(item.field, m)} · ${vintage}` : vintage,
      color: FORECAST_VINTAGE_COLORS[rank],
      unit: item.unit,
      points: item.points,
    }
  })
}

function seriesName(item: Series, multipleFields: boolean, chart: ExplorerChartConfig, m: Messages): string {
  const fieldLabel = explorerFieldLabel(item.field, m)
  const groupLabel = chart.groupLabels ? GROUP_LABELS[chart.groupLabels] : undefined
  const groupName = Object.values(item.group)
    .map((value) => (groupLabel ? groupLabel(value, m) : value))
    .join(' / ')
  if (!groupName) return fieldLabel
  return multipleFields ? `${fieldLabel} · ${groupName}` : groupName
}
