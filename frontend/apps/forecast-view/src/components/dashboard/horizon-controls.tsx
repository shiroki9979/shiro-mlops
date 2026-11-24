import { Button } from '@shiro-mlops/shared/ui/button'
import { Switch } from '@shiro-mlops/shared/ui/switch'
import { AUTO_REFRESH_INTERVAL_SEC } from '@/hooks/use-latest-issued-forecast'
import { useDashboardStore } from '@/store/dashboard-store'
import { Clock, MapPin, RefreshCw } from 'lucide-react'
import { type Messages, useMessages } from '@/i18n/messages'
import { HOURLY_PRESETS, WEEK_HOURS } from '@/lib/horizon-window'

function horizonPresets(horizonText: Messages['dashboard']['horizon']) {
  return [
    ...HOURLY_PRESETS.map((value) => ({ value, label: horizonText.hours(value) })),
    { value: WEEK_HOURS, label: horizonText.week },
  ]
}

export function HorizonControls() {
  const { horizonHours, setHorizonHours, autoRefresh, setAutoRefresh } = useDashboardStore()
  const m = useMessages()

  return (
    <div className="flex flex-wrap items-center justify-between gap-4 rounded-xl border border-slate-800 bg-slate-900/60 p-4 backdrop-blur-md">
      {/* Horizon Preset Buttons */}
      <div className="flex items-center gap-2">
        <span className="flex items-center gap-1.5 text-xs font-semibold text-slate-400 mr-1">
          <Clock className="h-3.5 w-3.5 text-cyan-400" />
          {m.dashboard.horizon.label}
        </span>
        <div className="flex flex-wrap items-center gap-1.5">
          {horizonPresets(m.dashboard.horizon).map((preset) => (
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

      {/* Prediction subject and auto refresh */}
      <div className="flex flex-wrap items-center gap-4">
        {/* The model forecasts nationwide load only, so the subject is fixed rather than selectable. */}
        <div className="flex items-center gap-2 text-xs text-slate-300">
          <MapPin className="h-3.5 w-3.5 text-slate-400" />
          <span>{m.dashboard.predictionSubject}</span>
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
            {m.dashboard.autoRefresh(AUTO_REFRESH_INTERVAL_SEC)}
          </label>
        </div>
      </div>
    </div>
  )
}
