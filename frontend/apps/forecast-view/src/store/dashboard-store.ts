import { create } from 'zustand'
import { persist } from 'zustand/middleware'

interface DashboardState {
  horizonHours: number
  autoRefresh: boolean
  refreshIntervalSec: number
  setHorizonHours: (hours: number) => void
  setAutoRefresh: (auto: boolean) => void
  setRefreshIntervalSec: (sec: number) => void
}

export const useDashboardStore = create<DashboardState>()(
  persist(
    (set) => ({
      horizonHours: 24,
      autoRefresh: false,
      refreshIntervalSec: 60,
      setHorizonHours: (horizonHours) => set({ horizonHours }),
      setAutoRefresh: (autoRefresh) => set({ autoRefresh }),
      setRefreshIntervalSec: (refreshIntervalSec) => set({ refreshIntervalSec }),
    }),
    {
      name: 'shiro-dashboard-settings',
    },
  ),
)
