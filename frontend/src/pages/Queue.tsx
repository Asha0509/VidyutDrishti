import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { post } from '../api'
import { ErrorBox, Loading, PageHead, StatusTag, TierTag } from '../components/ui'
import { inr, LAYER_LABEL, PATTERN_LABEL } from '../lib/format'
import { useQueue } from '../lib/queries'
import type { QueueItem } from '../lib/types'

export function useFeedback() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (b: { meter_id: string; was_anomaly: boolean; notes?: string; actual_kwh_observed?: number | null }) =>
      post<{ message: string }>('/feedback', { inspection_date: new Date().toISOString().slice(0, 10), ...b }),
    onSuccess: () => qc.invalidateQueries(),
  })
}

function Actions({ item }: { item: QueueItem }) {
  const fb = useFeedback()
  if (item.status !== 'pending') return <StatusTag status={item.status} />
  return (
    <div className="row" style={{ gap: '0.35rem', flexWrap: 'nowrap' }}>
      <button className="btn btn-sm" disabled={fb.isPending} onClick={() => fb.mutate({ meter_id: item.meter_id, was_anomaly: true })}
        aria-label={`Record theft confirmed at ${item.meter_id}`}>Theft found</button>
      <button className="btn btn-sm" disabled={fb.isPending} onClick={() => fb.mutate({ meter_id: item.meter_id, was_anomaly: false })}
        aria-label={`Record no theft at ${item.meter_id}`}>Nothing found</button>
      {fb.isError && <span className="small" style={{ color: 'var(--t-high)' }}>{(fb.error as Error).message}</span>}
    </div>
  )
}

export default function Queue() {
  const q = useQueue(200)
  const [tier, setTier] = useState('')
  const [zone, setZone] = useState('')
  const [status, setStatus] = useState('')
  const items = q.data?.items ?? []
  const zones = useMemo(() => [...new Set(items.map((i) => i.zone))].sort(), [items])
  const shown = items.filter((i) => (!tier || i.tier === tier) && (!zone || i.zone === zone) && (!status || i.status === status))
  const total = shown.reduce((s, i) => s + i.estimated_inr_lost, 0)

  return (
    <>
      <PageHead title="Inspection queue"
        sub="Every flagged meter, highest expected recoverable money first. Record the outcome after a visit; it updates the field results on the Accuracy page." />
      {q.isLoading && <Loading />}
      {q.isError && <ErrorBox error={q.error} retry={() => q.refetch()} />}
      {q.data && (
        <div className="card">
          <div className="spread" style={{ marginBottom: '0.9rem' }}>
            <div className="row">
              <label className="field"><span>Risk</span>
                <select className="select" value={tier} onChange={(e) => setTier(e.target.value)}>
                  <option value="">All</option><option value="HIGH">High</option><option value="MEDIUM">Medium</option><option value="REVIEW">Review</option>
                </select>
              </label>
              <label className="field"><span>Zone</span>
                <select className="select" value={zone} onChange={(e) => setZone(e.target.value)}>
                  <option value="">All</option>{zones.map((z) => <option key={z}>{z}</option>)}
                </select>
              </label>
              <label className="field"><span>Inspection</span>
                <select className="select" value={status} onChange={(e) => setStatus(e.target.value)}>
                  <option value="">All</option><option value="pending">Not inspected</option><option value="confirmed">Theft confirmed</option><option value="dismissed">No theft found</option>
                </select>
              </label>
            </div>
            <p className="small muted num">{shown.length} meters · {inr(total)} a month</p>
          </div>
          {shown.length === 0 ? <p className="muted">No meters match these filters.</p> : (
            <div className="table-wrap">
              <table className="data">
                <thead>
                  <tr><th>#</th><th>Meter</th><th>Risk</th><th>What changed</th><th>Checks agreeing</th><th className="r">₹ / month</th><th>Outcome</th></tr>
                </thead>
                <tbody>
                  {shown.map((i) => (
                    <tr key={i.meter_id}>
                      <td className="num">{i.rank}</td>
                      <td>
                        <Link to={`/app/meters/${i.meter_id}`} className="mono">{i.meter_id}</Link>
                        <div className="muted small">{i.zone} · {i.category}</div>
                      </td>
                      <td><TierTag tier={i.tier} /><div className="muted small num">{Math.round(i.confidence * 100)}% confidence</div></td>
                      <td>{PATTERN_LABEL[i.pattern]}<div className="muted small num">{i.baseline_kwh.toFixed(0)} → {i.recent_kwh.toFixed(0)} kWh/day</div></td>
                      <td className="small">{i.layers_fired.map((l) => LAYER_LABEL[l]?.code ?? l).join(' ')}</td>
                      <td className="r">{inr(i.estimated_inr_lost)}</td>
                      <td><Actions item={i} /></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}
    </>
  )
}
