import { useState } from 'react'
import { Link } from 'react-router-dom'
import { ErrorBox, Loading, ModeNote, PageHead, TierTag } from '../components/ui'
import { inr, shortDate } from '../lib/format'
import { useAlerts, useDigest } from '../lib/queries'
import type { Alert } from '../lib/types'

const TYPE_LABEL: Record<Alert['type'], string> = {
  new_flag: 'Newly flagged', escalation: 'Risk went up', balance_jump: 'Transformer losing more energy', cleared: 'No longer flagged',
}
const SEV: Record<Alert['severity'], { label: string; color: string }> = {
  critical: { label: 'Act today', color: 'var(--t-high)' },
  warning: { label: 'Watch', color: 'var(--t-medium)' },
  info: { label: 'For information', color: 'var(--t-review)' },
}

function Row({ a }: { a: Alert }) {
  const s = SEV[a.severity]
  return (
    <div className="spread" style={{ padding: '0.7rem 0', borderBottom: '1px solid var(--line)', alignItems: 'flex-start' }}>
      <div style={{ borderLeft: `4px solid ${s.color}`, paddingLeft: '0.75rem', minWidth: 0 }}>
        <div className="small" style={{ color: s.color, fontWeight: 600 }}>{s.label} · {TYPE_LABEL[a.type]}</div>
        <div style={{ overflowWrap: 'anywhere' }}>
          {a.meter_id ? <><Link className="mono" to={`/app/meters/${a.meter_id}`}>{a.meter_id}</Link> {a.title.replace(a.meter_id, '').trim()}</> : a.title}
        </div>
        <div className="small muted">{a.zone} · {a.dt_id}</div>
      </div>
      <div className="row" style={{ gap: '0.5rem' }}>
        {a.tier && a.type !== 'cleared' && <TierTag tier={a.tier} />}
        {a.estimated_monthly_loss_inr > 0 && <span className="small num">{inr(a.estimated_monthly_loss_inr)}/month</span>}
      </div>
    </div>
  )
}

export default function Alerts() {
  const [days, setDays] = useState(7)
  const [type, setType] = useState('')
  const alerts = useAlerts(days)
  const digest = useDigest(days)
  const shown = (alerts.data ?? []).filter((a) => !type || a.type === type)
  const byDate = shown.reduce<Record<string, Alert[]>>((acc, a) => { (acc[a.date] ??= []).push(a); return acc }, {})

  return (
    <>
      <PageHead title="Alerts"
        sub="Changes in the detector's output, day over day: new flags, rising risk, transformers suddenly losing more energy, and meters that recovered. Each meter alerts once per kind of change.">
        <label className="field"><span>Period</span>
          <select className="select" value={days} onChange={(e) => setDays(Number(e.target.value))}>
            <option value={1}>Last day</option><option value={3}>Last 3 days</option><option value={7}>Last 7 days</option><option value={14}>Last 14 days</option>
          </select>
        </label>
        <label className="field"><span>Kind</span>
          <select className="select" value={type} onChange={(e) => setType(e.target.value)}>
            <option value="">All</option>{Object.entries(TYPE_LABEL).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
          </select>
        </label>
      </PageHead>
      <div className="stack">
        <div className="card">
          <div className="card-head"><h3>Digest for the period</h3></div>
          {digest.isLoading && <Loading label="Writing the digest…" />}
          {digest.isError && <ErrorBox error={digest.error} retry={() => digest.refetch()} />}
          {digest.data && (
            <>
              <p className="msg-text">{digest.data.digest}</p>
              <ModeNote mode={digest.data.mode} provider={digest.data.provider} model={digest.data.model} fallback={digest.data.fallback_reason} />
            </>
          )}
        </div>
        <div className="card">
          {alerts.isLoading && <Loading />}
          {alerts.isError && <ErrorBox error={alerts.error} retry={() => alerts.refetch()} />}
          {alerts.data && shown.length === 0 && <p className="muted">No alerts in this period.</p>}
          {Object.entries(byDate).map(([d, items]) => (
            <section key={d} style={{ marginBottom: '0.8rem' }}>
              <h3 className="eyebrow" style={{ marginTop: '0.4rem' }}>{shortDate(d)} · {items.length} alert{items.length > 1 ? 's' : ''}</h3>
              {items.map((a, i) => <Row key={`${a.type}-${a.meter_id ?? a.dt_id}-${i}`} a={a} />)}
            </section>
          ))}
        </div>
      </div>
    </>
  )
}
