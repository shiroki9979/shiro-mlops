import { create } from 'zustand'
import { persist } from 'zustand/middleware'

interface DashboardState {
  horizonHours: number
  location: string
  showTemperature: boolean
  showHumidity: boolean
  autoRefresh: boolean
  refreshIntervalSec: number
  setHorizonHours: (hours: number) => void
  setLocation: (location: string) => void
  setShowTemperature: (show: boolean) => void
  setShowHumidity: (show: boolean) => void
  setAutoRefresh: (auto: boolean) => void
  setRefreshIntervalSec: (sec: number) => void
}

export const useDashboardStore = create<DashboardState>()(
  persist(
    (set) => ({
      horizonHours: 24,
      location: 'Taipei',
      showTemperature: true,
      showHumidity: false,
      autoRefresh: false,
      refreshIntervalSec: 60,
      setHorizonHours: (horizonHours) => set({ horizonHours }),
      setLocation: (location) => set({ location }),
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
