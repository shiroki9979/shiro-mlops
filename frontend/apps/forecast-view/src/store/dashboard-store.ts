import { create } from 'zustand'
import { persist } from 'zustand/middleware'

interface DashboardState {
  horizonHours: number
  autoRefresh: boolean
  setHorizonHours: (hours: number) => void
  setAutoRefresh: (auto: boolean) => void
}

export const useDashboardStore = create<DashboardState>()(
  persist(
    (set) => ({
      horizonHours: 24,
      autoRefresh: false,
      setHorizonHours: (horizonHours) => set({ horizonHours }),
      setAutoRefresh: (autoRefresh) => set({ autoRefresh }),
    }),
    {
      name: 'shiro-dashboard-settings',
      // Earlier versions also stored refreshIntervalSec; naming the persisted fields drops it from
      // storage on the next write, and nothing reads it in the meantime.
      partialize: ({ horizonHours, autoRefresh }) => ({ horizonHours, autoRefresh }),
    },
  ),
)
