import { Button } from '@/components/ui/button'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Switch } from '@/components/ui/switch'
import { useDashboardStore } from '@/store/dashboard-store'
import { Clock, Eye, MapPin, RefreshCw } from 'lucide-react'

const HORIZON_PRESETS = [
  { label: '24 小時', value: 24 },
  { label: '48 小時', value: 48 },
  { label: '72 小時', value: 72 },
  { label: '7 天 (168h)', value: 168 },
]

const LOCATIONS = [
  { label: '台北 (北部區域)', value: 'Taipei' },
  { label: '台中 (中部區域)', value: 'Taichung' },
  { label: '高雄 (南部區域)', value: 'Kaohsiung' },
]

export function HorizonControls() {
  const {
    horizonHours,
    setHorizonHours,
    location,
    setLocation,
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

      {/* Location and Series Toggles */}
      <div className="flex flex-wrap items-center gap-4">
        {/* Location selector */}
        <div className="flex items-center gap-2">
          <MapPin className="h-3.5 w-3.5 text-slate-400" />
          <div className="w-40">
            <Select value={location} onValueChange={(val) => setLocation(val)}>
              <SelectTrigger className="h-8 text-xs bg-slate-900 border-slate-700">
                <SelectValue placeholder="選擇地區" />
              </SelectTrigger>
              <SelectContent>
                {LOCATIONS.map((loc) => (
                  <SelectItem key={loc.value} value={loc.value} className="text-xs">
                    {loc.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
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
