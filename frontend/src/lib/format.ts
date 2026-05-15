import type { Pattern, Tier } from './types'

export const inr = (v: number | null | undefined) =>
  v == null ? '–' : `₹${Math.round(v).toLocaleString('en-IN')}`
export const pct = (v: number | null | undefined, digits = 0) => (v == null ? '–' : `${(v * 100).toFixed(digits)}%`)

export const PATTERN_LABEL: Record<Pattern, string> = {
  flatline: 'Flat at zero',
  sudden_drop: 'Sudden drop',
  gradual_decline: 'Gradual decline',
  consumption_drop: 'Drop',
  normal: 'Normal',
}

export const TIER_LABEL: Record<Tier | 'LOW', string> = {
  HIGH: 'High risk', MEDIUM: 'Medium risk', REVIEW: 'Review', NORMAL: 'Normal', LOW: 'Low risk',
}

export const LAYER_LABEL: Record<string, { code: string; name: string }> = {
  dt_balance: { code: 'L0', name: 'Transformer balance' },
  self_history: { code: 'L1', name: 'Own history' },
  peer_comparison: { code: 'L2', name: 'Neighbours on the same transformer' },
  isolation_forest: { code: 'L3', name: 'Outlier model' },
}

export function shortDate(iso: string) {
  return new Date(iso + (iso.length === 10 ? 'T00:00:00' : '')).toLocaleDateString('en-IN', { day: 'numeric', month: 'short' })
}
