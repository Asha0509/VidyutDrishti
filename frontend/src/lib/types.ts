export type Tier = 'HIGH' | 'MEDIUM' | 'REVIEW' | 'NORMAL'
export type Pattern = 'flatline' | 'sudden_drop' | 'gradual_decline' | 'consumption_drop' | 'normal'

export interface Layer { name: string; fired: boolean; strength: number; value: number | null; detail: string }

export interface QueueItem {
  rank: number; meter_id: string; dt_id: string; feeder_id: string; zone: string; confidence: number; tier: Tier
  pattern: Pattern; estimated_inr_lost: number; drop_pct: number; baseline_kwh: number; recent_kwh: number
  category: string; layers_fired: string[]; description: string; status: 'pending' | 'confirmed' | 'dismissed'
}

export interface Overview {
  date: string; meters: number; dts: number; flagged: number; pending: number; estimated_monthly_loss_inr: number
  zones_at_risk: number; zones: number; by_tier: Record<string, number>; by_pattern: Record<string, number>
  layers_fired: Record<string, number>; confidence_histogram: { bucket: string; meters: number }[]
}

export interface Zone {
  id: string; name: string; dt_id: string; feeder_id: string; place: string; lat: number; lng: number
  meter_count: number; flagged: number; high: number; estimated_inr_lost: number; risk: Tier | 'LOW'
  risk_score: number; pending_inspections: number; total_kwh_today: number
}

export interface MeterSummary {
  meter_id: string; dt_id: string; zone: string; category: string; confidence: number; tier: Tier
  pattern: Pattern; drop_pct: number; flagged: boolean
}

export interface MeterDetail extends MeterSummary {
  feeder_id: string; date: string; baseline_kwh: number; recent_kwh: number; est_monthly_loss_inr: number
  layers: Layer[]; status: string; series: { date: string; kwh: number | null; peer_median: number | null; baseline: number }[]
  peers: string[]; place: string
}

export interface Step { kind: string; name: string; summary?: string; args?: Record<string, unknown>; ms?: number; provider?: string; model?: string; failovers?: string[] }

export interface Brief {
  meter_id: string; likely_cause: string; cause_name: string; confidence: 'low' | 'medium' | 'high'; summary: string
  evidence: string[]; field_checks: string[]; safety_note: string; mode: 'agent' | 'rules'; provider: string | null
  model: string | null; fallback_reason: string | null; latency_ms: number; steps: Step[]; detector_pattern: string
  cached?: boolean
}

export interface CopilotAnswer {
  answer: string; follow_ups: string[]; mode: 'agent' | 'rules'; provider: string | null; model: string | null
  llm_calls: number; tool_calls: number; tools_used: string[]; fallback_reason: string | null; latency_ms: number
  steps: Step[]
}

export interface Alert {
  date: string; type: 'new_flag' | 'escalation' | 'balance_jump' | 'cleared'; severity: 'critical' | 'warning' | 'info'
  meter_id: string | null; zone: string; dt_id: string; tier: Tier | null; title: string; estimated_monthly_loss_inr: number
}

export interface AIStatus { llm_providers: string[]; llm_models: Record<string, string>; agent_enabled: boolean; data_ready: boolean; rate_limit: string }
