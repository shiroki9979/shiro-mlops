import { useMemo } from 'react'
import { useNavigate, useRouterState } from '@tanstack/react-router'
import { defaultWindow, toRfc3339 } from '@/lib/data-explorer'
import type { ExplorerDatasetConfig } from './catalog'

export function useExplorerSearch(dataset: ExplorerDatasetConfig) {
  const router = useRouterState()
  const navigate = useNavigate()
  const search = router.location.search as Record<string, string | undefined>
  const windowDefaults = useMemo(
    () => defaultWindow(dataset.defaultHours, dataset.lookAheadHours ?? 0),
    [dataset.defaultHours, dataset.lookAheadHours],
  )
  const start = search.start || toRfc3339(windowDefaults.start)
  const end = search.end || toRfc3339(windowDefaults.end)
  const filterValues = Object.fromEntries(
    dataset.filters.map((field) => [field.key, search[field.key]]),
  ) as Record<string, string | undefined>
  const params = {
    start,
    end,
    cursor: search.cursor,
    ...filterValues,
  }

  const updateSearch = (patch: Record<string, string | undefined>) => {
    const next: Record<string, string | undefined> = {
      ...search,
      start,
      end,
      ...filterValues,
      ...patch,
    }
    Object.keys(next).forEach((key) => {
      if (!next[key]) delete next[key]
    })
    void navigate({ to: dataset.path as never, search: next as never })
  }

  return { start, end, filterValues, params, updateSearch }
}
