// Category colours for every Data Explorer chart, defined once so a region, unit type,
// station or audit status keeps the same colour on every page. Each colour keeps at
// least 3:1 contrast against CHART_SURFACE (WCAG non-text contrast), checked by
// tests/unit/chart-palette.test.ts.

export type CategoryPalette = Readonly<Record<string, string>>

// Effective console card colour: bg-slate-900/70 composited over the bg-slate-950 layout.
export const CHART_SURFACE = '#0b1224'
export const CHART_GRID = '#334155'
export const CHART_AXIS = '#64748b'
export const CHART_GAP_BAND = '#64748b'
// Buckets where only some series have data, e.g. a region missing from a regional slot.
export const CHART_INCOMPLETE_BAND = '#f59e0b'
// The pending brush range, in the console accent so it reads as a selection rather than data.
export const CHART_BRUSH = '#22d3ee'

// Ungrouped or open-ended series (subjects, unknown keys) take these in order.
export const SERIES_COLORS = ['#22d3ee', '#fbbf24', '#f472b6', '#34d399', '#a78bfa', '#fb923c'] as const

// SYNC: REGIONAL_SUPPLY_DEMAND_REGIONS in src/shiro_mlops/data/taipower_regional_supply_demand.py
export const REGION_COLORS: CategoryPalette = {
  北部: '#22d3ee',
  中部: '#fbbf24',
  南部: '#fb7185',
  東部: '#34d399',
}

// Families share a hue and differ in lightness: the private gas and coal plants and the
// storage load sit next to their public counterpart.
export const UNIT_TYPE_COLORS: CategoryPalette = {
  燃氣: '#f97316',
  '民營電廠-燃氣': '#fdba74',
  燃煤: '#8b5cf6',
  '民營電廠-燃煤': '#c4b5fd',
  儲能: '#14b8a6',
  '儲能負載(Energy Storage System Load)': '#99f6e4',
  太陽能: '#facc15',
  風力: '#38bdf8',
  水力: '#3b82f6',
  燃料油: '#f87171',
  汽電共生: '#e879f9',
  其它再生能源: '#4ade80',
}

// SYNC: DEFAULT_CWA_LOCATIONS in src/shiro_mlops/data/cwa_client.py (stations outside it use SERIES_COLORS)
export const STATION_COLORS: CategoryPalette = {
  '466920': '#67e8f9',
  '467490': '#fcd34d',
  '467441': '#f9a8d4',
}

export const AUDIT_STATUS_COLORS: CategoryPalette = {
  complete: '#34d399',
  incomplete: '#fbbf24',
}

// Forecast vintages are ordered newest first; the newest is the brightest.
export const FORECAST_VINTAGE_COLORS = ['#a5f3fc', '#67e8f9', '#22d3ee', '#06b6d4', '#0891b2'] as const

export const CATEGORY_PALETTES = {
  region: REGION_COLORS,
  unit_type: UNIT_TYPE_COLORS,
  station_id: STATION_COLORS,
  status: AUDIT_STATUS_COLORS,
} as const satisfies Record<string, CategoryPalette>

export type CategoryPaletteKey = keyof typeof CATEGORY_PALETTES

// A named category keeps its own colour; anything else falls back to the series order.
export function categoryColor(palette: CategoryPalette | undefined, key: string | undefined, index: number): string {
  const named = palette && key !== undefined ? palette[key] : undefined
  return named ?? SERIES_COLORS[index % SERIES_COLORS.length]
}
