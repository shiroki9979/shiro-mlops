import { create } from 'zustand'
import { persist } from 'zustand/middleware'

interface DashboardState {
  horizonHours: number
  showTemperature: boolean
  showHumidity: boolean
  autoRefresh: boolean
  refreshIntervalSec: number
  setHorizonHours: (hours: number) => void
  setShowTemperature: (show: boolean) => void
  setShowHumidity: (show: boolean) => void
  setAutoRefresh: (auto: boolean) => void
  setRefreshIntervalSec: (sec: number) => void
}

export const useDashboardStore = create<DashboardState>()(
  persist(
    (set) => ({
      horizonHours: 24,
      showTemperature: true,
      showHumidity: false,
      autoRefresh: false,
      refreshIntervalSec: 60,
      setHorizonHours: (horizonHours) => set({ horizonHours }),
      setShowTemperature: (showTemperature) => set({ showTemperature }),
      setShowHumidity: (showHumidity) => set({ showHumidity }),
      setAutoRefresh: (autoRefresh) => set({ autoRefresh }),
      setRefreshIntervalSec: (refreshIntervalSec) => set({ refreshIntervalSec }),
    }),
    {
      name: 'shiro-dashboard-settings',
    },
  ),
)
