import type { ReactNode } from 'react'
import { ApiError } from '../api'
import { TIER_LABEL } from '../lib/format'
import type { Tier } from '../lib/types'

export function TierTag({ tier }: { tier: Tier | 'LOW' }) {
  return <span className={`tag tag-${tier}`}>{TIER_LABEL[tier]}</span>
}

export function StatusTag({ status }: { status: string }) {
  const label = status === 'confirmed' ? 'Theft confirmed' : status === 'dismissed' ? 'No theft found' : 'Not inspected'
  return <span className={`tag tag-${status}`}>{label}</span>
}

export function Loading({ label = 'Loading…' }: { label?: string }) {
  return <p className="muted" role="status">{label}</p>
}

export function ErrorBox({ error, retry }: { error: unknown; retry?: () => void }) {
  const msg = error instanceof ApiError || error instanceof Error ? error.message : 'Something went wrong.'
  return (
    <div className="notice error" role="alert">
      <div className="spread">
        <span>{msg}</span>
        {retry && <button className="btn btn-sm" onClick={retry}>Try again</button>}
      </div>
    </div>
  )
}

export function Kpi({ label, value, note, accent }: { label: string; value: ReactNode; note?: ReactNode; accent?: boolean }) {
  return (
    <div className={`kpi${accent ? ' accent' : ''}`}>
      <div className="kpi-label">{label}</div>
      <div className="kpi-value">{value}</div>
      {note && <div className="kpi-note">{note}</div>}
    </div>
  )
}

export function PageHead({ title, sub, children }: { title: string; sub?: ReactNode; children?: ReactNode }) {
  return (
    <header className="page-head">
      <div>
        <h1>{title}</h1>
        {sub && <p>{sub}</p>}
      </div>
      {children && <div className="row">{children}</div>}
    </header>
  )
}

interface TipRow { name: string; value: string; color?: string }
export function ChartTip({ title, rows }: { title: string; rows: TipRow[] }) {
  return (
    <div className="tooltip">
      <b>{title}</b>
      {rows.map((r) => (
        <div key={r.name}>
          <span>{r.color && <i className="dot" style={{ background: r.color }} />}{r.name}</span>
          <span className="num">{r.value}</span>
        </div>
      ))}
    </div>
  )
}

export function ModeNote({ mode, provider, model, fallback, latency }: {
  mode: 'agent' | 'rules'; provider?: string | null; model?: string | null; fallback?: string | null; latency?: number
}) {
  return (
    <span className="msg-meta">
      <span className="tag tag-plain">{mode === 'agent' ? 'AI model' : 'Rule-based'}</span>
      {mode === 'agent' && model && <span className="mono">{provider} · {model}</span>}
      {mode === 'rules' && fallback && <span>{fallbackText(fallback)}</span>}
      {latency != null && <span className="num">{latency < 1000 ? `${Math.round(latency)} ms` : `${(latency / 1000).toFixed(1)} s`}</span>}
    </span>
  )
}

function fallbackText(code: string) {
  const map: Record<string, string> = {
    no_llm_provider: 'No AI model is configured on this server.',
    agent_failed: "The AI model didn't answer, so rules were used.",
    llm_disabled: 'AI switched off for this request.',
  }
  return map[code] ?? code
}

export function BrandMark() {
  return (
    <svg className="brand-mark" viewBox="0 0 32 32" aria-hidden="true">
      <rect width="32" height="32" rx="6" fill="#F2B705" />
      <path d="M18 4 8 18h7l-2 10 11-15h-7z" fill="#142030" />
    </svg>
  )
}
