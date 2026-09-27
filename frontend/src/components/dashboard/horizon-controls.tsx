import { Button } from '@/components/ui/button'
import { Switch } from '@/components/ui/switch'
import { useDashboardStore } from '@/store/dashboard-store'
import { Clock, Eye, MapPin, RefreshCw } from 'lucide-react'

const HORIZON_PRESETS = [
  { label: '24 小時', value: 24 },
  { label: '48 小時', value: 48 },
  { label: '72 小時', value: 72 },
  { label: '7 天 (168h)', value: 168 },
]

export function HorizonControls() {
  const {
    horizonHours,
    setHorizonHours,
    showTemperature,
    setShowTemperature,
    showHumidity,
    setShowHumidity,
    autoRefresh,
    setAutoRefresh,
  } = useDashboardStore()

  return (
    <div className="flex flex-wrap items-center justify-between gap-4 rounded-xl border border-slate-800 bg-slate-900/60 p-4 backdrop-blur-md">
      {/* Horizon Preset Buttons */}
      <div className="flex items-center gap-2">
        <span className="flex items-center gap-1.5 text-xs font-semibold text-slate-400 mr-1">
          <Clock className="h-3.5 w-3.5 text-cyan-400" />
          預測時效：
        </span>
        <div className="flex flex-wrap items-center gap-1.5">
          {HORIZON_PRESETS.map((preset) => (
            <Button
              key={preset.value}
              variant={horizonHours === preset.value ? 'default' : 'outline'}
              size="sm"
              onClick={() => setHorizonHours(preset.value)}
              className="text-xs h-8 px-3"
            >
              {preset.label}
            </Button>
          ))}
        </div>
      </div>

      {/* Prediction subject and Series Toggles */}
      <div className="flex flex-wrap items-center gap-4">
        {/* The model forecasts nationwide load only, so the subject is fixed rather than selectable. */}
        <div className="flex items-center gap-2 text-xs text-slate-300">
          <MapPin className="h-3.5 w-3.5 text-slate-400" />
          <span>預測對象：全台</span>
        </div>

        <div className="h-4 w-px bg-slate-800" />

        {/* Dual Axis Toggles */}
        <div className="flex items-center gap-3 text-xs">
          <div className="flex items-center gap-1.5">
            <Switch
              id="temp-toggle"
              checked={showTemperature}
              onCheckedChange={setShowTemperature}
            />
            <label
              htmlFor="temp-toggle"
              className="cursor-pointer text-slate-300 flex items-center gap-1 select-none"
            >
              <Eye className="h-3.5 w-3.5 text-amber-400" />
              氣溫曲線 (°C)
            </label>
          </div>

          <div className="flex items-center gap-1.5">
            <Switch
              id="humidity-toggle"
              checked={showHumidity}
              onCheckedChange={setShowHumidity}
            />
            <label
              htmlFor="humidity-toggle"
              className="cursor-pointer text-slate-300 select-none"
            >
              相對濕度 (%)
            </label>
          </div>
        </div>

        <div className="h-4 w-px bg-slate-800" />

        {/* Auto Refresh toggle */}
        <div className="flex items-center gap-1.5 text-xs">
          <Switch
            id="auto-refresh"
            checked={autoRefresh}
            onCheckedChange={setAutoRefresh}
          />
          <label
            htmlFor="auto-refresh"
            className="cursor-pointer text-slate-300 flex items-center gap-1 select-none"
          >
            <RefreshCw className={`h-3 w-3 ${autoRefresh ? 'text-cyan-400' : 'text-slate-500'}`} />
            自動輪詢 (60s)
          </label>
        </div>
      </div>
    </div>
  )
}
