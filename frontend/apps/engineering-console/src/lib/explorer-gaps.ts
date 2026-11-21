const MS_PER_MINUTE = 60_000
// Station-observation gaps arrive as `<RFC 3339 slot>:<station_id>`; the slot itself ends in `+08:00`.
const STATION_SLOT_PATTERN = /^(.+[+-]\d{2}:\d{2}):([^:]+)$/

export interface GapRange {
  start: string
  end: string
  slotCount: number
}

export interface GapGroup {
  stationId?: string
  ranges: GapRange[]
}

// Gaps are the dataset's expected slots, so consecutive means exactly one cadence apart.
export function mergeGapSlots(slots: string[], cadenceMinutes: number): GapRange[] {
  const sorted = [...slots].sort((left, right) => Date.parse(left) - Date.parse(right))
  const ranges: GapRange[] = []
  for (const slot of sorted) {
    const last = ranges.at(-1)
    if (last && Date.parse(slot) - Date.parse(last.end) === cadenceMinutes * MS_PER_MINUTE) {
      last.end = slot
      last.slotCount += 1
    } else {
      ranges.push({ start: slot, end: slot, slotCount: 1 })
    }
  }
  return ranges
}

export function groupGapSlots(slots: string[], cadenceMinutes: number, byStation: boolean): GapGroup[] {
  if (!byStation) return [{ ranges: mergeGapSlots(slots, cadenceMinutes) }]
  const slotsByStation = new Map<string, string[]>()
  for (const entry of slots) {
    const match = STATION_SLOT_PATTERN.exec(entry)
    if (!match) throw new Error(`Malformed station gap slot: ${entry}`)
    const [, slot, stationId] = match
    slotsByStation.set(stationId, [...(slotsByStation.get(stationId) ?? []), slot])
  }
  return [...slotsByStation.entries()]
    .sort(([left], [right]) => left.localeCompare(right))
    .map(([stationId, stationSlots]) => ({
      stationId,
      ranges: mergeGapSlots(stationSlots, cadenceMinutes),
    }))
}
