import { useQuery } from '@tanstack/react-query'
import { get } from '../api'
import type { AIStatus, Alert, MeterDetail, MeterSummary, Overview, QueueItem, Zone } from './types'

export interface BalanceRow { dt_id: string; date: string; kwh_in: number; kwh_metered: number; unmetered_pct: number }

export const useOverview = () => useQuery({ queryKey: ['overview'], queryFn: () => get<Overview>('/overview') })
export const useQueue = (limit = 200) =>
  useQuery({ queryKey: ['queue', limit], queryFn: () => get<{ date: string; items: QueueItem[] }>(`/queue/daily?limit=${limit}`) })
export const useMeters = () =>
  useQuery({ queryKey: ['meters'], queryFn: () => get<{ meters: MeterSummary[] }>('/meters'), select: (d) => d.meters })
export const useMeter = (id: string) =>
  useQuery({ queryKey: ['meter', id], queryFn: () => get<MeterDetail>(`/meters/${encodeURIComponent(id)}/status`), retry: false })
export const useZones = () =>
  useQuery({ queryKey: ['zones'], queryFn: () => get<{ date: string; zones: Zone[] }>('/zones/summary'), select: (d) => d.zones })
export const useBalance = (days = 30) =>
  useQuery({ queryKey: ['balance', days], queryFn: () => get<{ rows: BalanceRow[] }>(`/dt/balance?days=${days}`), select: (d) => d.rows })
export const useAiStatus = () => useQuery({ queryKey: ['ai-status'], queryFn: () => get<AIStatus>('/ai/status') })
export const useAlerts = (days = 7) =>
  useQuery({ queryKey: ['alerts', days], queryFn: () => get<{ alerts: Alert[] }>(`/ai/alerts?days=${days}`), select: (d) => d.alerts })

export interface Digest { days: number; alert_count: number; digest: string; mode: 'agent' | 'rules'; provider: string | null; model: string | null; fallback_reason: string | null; latency_ms: number }
export const useDigest = (days = 1) =>
  useQuery({ queryKey: ['digest', days], queryFn: () => get<Digest>(`/ai/alerts/digest?days=${days}`), staleTime: 5 * 60_000, retry: false })

/** Latest-day balance row per transformer. */
export function latestBalance(rows: BalanceRow[] | undefined): Record<string, BalanceRow> {
  const out: Record<string, BalanceRow> = {}
  for (const r of rows ?? []) if (!out[r.dt_id] || out[r.dt_id].date < r.date) out[r.dt_id] = r
  return out
}
