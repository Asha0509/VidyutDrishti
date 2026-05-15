import type { ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { ErrorBox, Kpi, Loading, ModeNote, PageHead, TierTag } from '../components/ui'
import { inr, LAYER_LABEL, PATTERN_LABEL, shortDate } from '../lib/format'
import { latestBalance, useBalance, useDigest, useOverview, useQueue, useZones } from '../lib/queries'

function BarList({ rows, color, fmt }: { rows: { key: string; label: ReactNode; value: number }[]; color: string; fmt: (v: number) => string }) {
  const max = Math.max(...rows.map((r) => r.value), 1)
  return (
    <div className="stack" style={{ gap: '0.65rem' }}>
      {rows.map((r) => (
        <div key={r.key}>
          <div className="spread small"><span>{r.label}</span><span className="num">{fmt(r.value)}</span></div>
          <div className="bar-track"><div className="bar-fill" style={{ width: `${(r.value / max) * 100}%`, background: color }} /></div>
        </div>
      ))}
    </div>
  )
}

function Digest() {
  const d = useDigest(1)
  return (
    <div className="card">
      <div className="card-head">
        <h3>Today's digest</h3>
        <Link to="/app/alerts" className="small">All alerts</Link>
      </div>
      {d.isLoading && <Loading label="Writing the digest…" />}
      {d.isError && <ErrorBox error={d.error} retry={() => d.refetch()} />}
      {d.data && (
        <>
          <p className="msg-text">{d.data.digest}</p>
          <ModeNote mode={d.data.mode} provider={d.data.provider} model={d.data.model} fallback={d.data.fallback_reason} />
        </>
      )}
    </div>
  )
}

export default function Dashboard() {
  const ov = useOverview()
  const q = useQueue(5)
  const bal = useBalance(7)
  const zones = useZones()
  if (ov.isLoading) return <Loading />
  if (ov.isError) return <ErrorBox error={ov.error} retry={() => ov.refetch()} />
  const o = ov.data!
  const latest = Object.values(latestBalance(bal.data)).sort((a, b) => b.unmetered_pct - a.unmetered_pct)
  const place = (dt: string) => zones.data?.find((z) => z.dt_id === dt)?.place

  return (
    <>
      <PageHead title="Overview" sub={`Network status on ${shortDate(o.date)}. Estimates are monthly, from each flagged meter's drop and tariff.`}>
        <Link className="btn btn-primary" to="/app/queue">Open the inspection queue</Link>
      </PageHead>
      <div className="stack">
        <div className="kpis">
          <Kpi accent label="Estimated monthly loss" value={inr(o.estimated_monthly_loss_inr)} note={`across ${o.flagged} flagged meters`} />
          <Kpi label="Meters flagged" value={<>{o.flagged}<span className="muted" style={{ fontSize: '1.2rem' }}> / {o.meters}</span></>}
            note={`${o.by_tier.HIGH ?? 0} high · ${o.by_tier.MEDIUM ?? 0} medium · ${o.by_tier.REVIEW ?? 0} review`} />
          <Kpi label="Awaiting inspection" value={o.pending} note="flagged and not yet visited" />
          <Kpi label="Zones at risk" value={<>{o.zones_at_risk}<span className="muted" style={{ fontSize: '1.2rem' }}> / {o.zones}</span></>} note="medium or high risk" />
        </div>

        <div className="grid grid-2">
          <div className="card">
            <div className="card-head">
              <h3>Inspect first</h3>
              <Link to="/app/queue" className="small">Full queue</Link>
            </div>
            {q.isError ? <ErrorBox error={q.error} /> : (
              <div className="table-wrap">
                <table className="data">
                  <thead><tr><th>#</th><th>Meter</th><th>Risk</th><th>Pattern</th><th className="r">₹ / month</th></tr></thead>
                  <tbody>
                    {q.data?.items.map((i) => (
                      <tr key={i.meter_id}>
                        <td className="num">{i.rank}</td>
                        <td><Link to={`/app/meters/${i.meter_id}`} className="mono">{i.meter_id}</Link><div className="muted small">{i.zone}</div></td>
                        <td><TierTag tier={i.tier} /></td>
                        <td>{PATTERN_LABEL[i.pattern]}</td>
                        <td className="r">{inr(i.estimated_inr_lost)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
          <Digest />
        </div>

        <div className="grid grid-2">
          <div className="card">
            <div className="card-head">
              <h3>Unmetered energy by transformer</h3>
              <p>Share of incoming energy no meter recorded, latest day</p>
            </div>
            {bal.isLoading ? <Loading /> : (
              <BarList color="var(--s-amber)" fmt={(v) => `${v.toFixed(1)}%`}
                rows={latest.map((r) => ({ key: r.dt_id, value: r.unmetered_pct,
                  label: <><b>{r.dt_id}</b> <span className="muted">{place(r.dt_id)}</span></> }))} />
            )}
            <p className="small muted" style={{ marginTop: '0.8rem' }}>
              A few percent is normal technical loss. <Link to="/app/zones">See each transformer</Link>
            </p>
          </div>
          <div className="card">
            <div className="card-head">
              <h3>Which checks fired</h3>
              <p>Meters where each detection layer found evidence</p>
            </div>
            <BarList color="var(--s-blue)" fmt={(v) => `${v} meters`}
              rows={Object.entries(LAYER_LABEL).map(([k, l]) => ({ key: k, value: o.layers_fired[k] ?? 0,
                label: <><b>{l.code}</b> {l.name}</> }))} />
            <div className="row small" style={{ marginTop: '1rem' }}>
              {Object.entries(o.by_pattern).map(([p, n]) => (
                <span key={p} className="tag tag-plain">{PATTERN_LABEL[p as keyof typeof PATTERN_LABEL] ?? p}: {n}</span>
              ))}
            </div>
          </div>
        </div>
      </div>
    </>
  )
}
