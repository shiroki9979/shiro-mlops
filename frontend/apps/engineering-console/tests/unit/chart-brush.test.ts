import { describe, expect, it, vi } from 'vitest'
import { act, renderHook } from '@testing-library/react'
import { useChartBrush } from '@/components/data-explorer/chart-brush'

const at = (activeLabel: unknown) => ({ activeLabel })

describe('useChartBrush', () => {
  it('keeps the same selection while the pointer moves inside one bucket', () => {
    // Every new selection object re-renders the chart card and its whole series.
    const { result } = renderHook(() => useChartBrush(vi.fn()))
    act(() => result.current.handlers.onMouseDown(at(1000)))
    act(() => result.current.handlers.onMouseMove(at(2000)))
    const afterEnteringBucket = result.current.selection

    act(() => result.current.handlers.onMouseMove(at(2000)))
    act(() => result.current.handlers.onMouseMove(at(2000)))

    expect(result.current.selection).toBe(afterEnteringBucket)
    expect(result.current.selection).toEqual({ from: 1000, to: 2000 })
  })

  it('keeps the selection when the pointer crosses a spot with no bucket', () => {
    const { result } = renderHook(() => useChartBrush(vi.fn()))
    act(() => result.current.handlers.onMouseDown(at(1000)))
    act(() => result.current.handlers.onMouseMove(at(2000)))
    const selection = result.current.selection

    act(() => result.current.handlers.onMouseMove(null))
    act(() => result.current.handlers.onMouseMove(at('not-a-number')))

    expect(result.current.selection).toBe(selection)
  })

  it('extends the selection to each new bucket the pointer reaches', () => {
    const { result } = renderHook(() => useChartBrush(vi.fn()))
    act(() => result.current.handlers.onMouseDown(at(1000)))

    act(() => result.current.handlers.onMouseMove(at(2000)))
    act(() => result.current.handlers.onMouseMove(at(3000)))

    expect(result.current.selection).toEqual({ from: 1000, to: 3000 })
  })

  it('reports the dragged range on release and clears the selection', () => {
    const onSelect = vi.fn()
    const { result } = renderHook(() => useChartBrush(onSelect))
    act(() => result.current.handlers.onMouseDown(at(3000)))
    act(() => result.current.handlers.onMouseMove(at(2000)))

    act(() => result.current.handlers.onMouseUp(at(1000)))

    expect(onSelect).toHaveBeenCalledExactlyOnceWith({ from: 3000, to: 1000 })
    expect(result.current.selection).toBeNull()
  })

  it('treats a press and release on one bucket as a click', () => {
    const onSelect = vi.fn()
    const { result } = renderHook(() => useChartBrush(onSelect))
    act(() => result.current.handlers.onMouseDown(at(1000)))

    act(() => result.current.handlers.onMouseUp(at(1000)))

    expect(onSelect).not.toHaveBeenCalled()
    expect(result.current.selection).toBeNull()
  })

  it('ignores movement before a press and a press outside the plot', () => {
    const { result } = renderHook(() => useChartBrush(vi.fn()))

    act(() => result.current.handlers.onMouseMove(at(1000)))
    expect(result.current.selection).toBeNull()

    act(() => result.current.handlers.onMouseDown(null))
    expect(result.current.selection).toBeNull()
  })

  it('drops the selection when the pointer leaves the chart', () => {
    const onSelect = vi.fn()
    const { result } = renderHook(() => useChartBrush(onSelect))
    act(() => result.current.handlers.onMouseDown(at(1000)))
    act(() => result.current.handlers.onMouseMove(at(2000)))

    act(() => result.current.handlers.onMouseLeave())
    act(() => result.current.handlers.onMouseUp(at(3000)))

    expect(result.current.selection).toBeNull()
    expect(onSelect).not.toHaveBeenCalled()
  })
})
