import { useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { useMutation } from '@tanstack/react-query'
import { Bar, BarChart, CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { ApiError, post } from '../api'
import Trace from '../components/Trace'
import { ChartTip, ErrorBox, Kpi, Loading, ModeNote, PageHead, StatusTag, TierTag } from '../components/ui'
import { inr, LAYER_LABEL, PATTERN_LABEL, shortDate } from '../lib/format'
import { useBalance, useMeter, useMeters } from '../lib/queries'
import type { Brief, Layer, MeterDetail } from '../lib/types'
import { useFeedback } from './Queue'

const C = { meter: '#2F6DB5', peers: '#14917A', gap: '#C27C0E', ink: '#142030', grid: '#E3E8EE', axis: '#5d6b7c' }
const axisProps = { tick: { fontSize: 12, fill: C.axis }, tickLine: false, axisLine: { stroke: C.grid } }
const kwh = (v: unknown) => (typeof v === 'number' ? `${v.toFixed(1)} kWh` : '–')

function UsageChart({ m }: { m: MeterDetail }) {
  return (
    <div className="card">
      <div className="card-head">
        <h3>Daily consumption</h3>
        <p>kWh per day, last {m.series.length} days</p>
      </div>
      <div className="legend">
        <span><i style={{ background: C.meter }} />{m.meter_id}</span>
        <span><i style={{ background: C.peers }} />Median of its neighbours</span>
        <span><i className="dash" />Its own baseline</span>
      </div>
      <div className="chart">
        <ResponsiveContainer>
          <LineChart data={m.series} margin={{ top: 8, right: 8, bottom: 0, left: -12 }}>
            <CartesianGrid stroke={C.grid} vertical={false} />
            <XAxis dataKey="date" tickFormatter={shortDate} minTickGap={36} {...axisProps} />
            <YAxis {...axisProps} width={52} />
            <Tooltip content={({ active, payload, label }) => active && payload?.length ? (
              <ChartTip title={shortDate(String(label))} rows={[
                { name: m.meter_id, value: kwh(payload[0]?.payload.kwh), color: C.meter },
                { name: 'Neighbours (median)', value: kwh(payload[0]?.payload.peer_median), color: C.peers },
                { name: 'Baseline', value: kwh(payload[0]?.payload.baseline), color: C.ink },
              ]} />) : null} />
            <Line dataKey="baseline" stroke={C.ink} strokeWidth={1.5} strokeDasharray="5 4" dot={false} isAnimationActive={false} />
            <Line dataKey="peer_median" stroke={C.peers} strokeWidth={2} dot={false} isAnimationActive={false} connectNulls />
            <Line dataKey="kwh" stroke={C.meter} strokeWidth={2.5} dot={false} isAnimationActive={false} connectNulls
              activeDot={{ r: 5, stroke: '#fff', strokeWidth: 2 }} />
          </LineChart>
        </ResponsiveContainer>
      </div>
    </div>
  )
}

function LayerCard({ l }: { l: Layer }) {
  const meta = LAYER_LABEL[l.name] ?? { code: '?', name: l.name }
  return (
    <div className={`layer${l.fired ? ' fired' : ''}`}>
      <div className="spread">
        <span className="row" style={{ gap: '0.5rem' }}><span className="layer-code">{meta.code}</span><b>{meta.name}</b></span>
        <span className="small">{l.fired ? 'Found evidence' : 'Nothing unusual'}</span>
      </div>
      <p className="small">{l.detail}</p>
      <div className="bar-track" title={`Strength ${Math.round(l.strength * 100)}%`}>
        <div className="bar-fill" style={{ width: `${l.strength * 100}%`, background: l.fired ? 'var(--t-high)' : 'var(--line-strong)' }} />
      </div>
    </div>
  )
}

function BriefCard({ id }: { id: string }) {
  const m = useMutation({ mutationFn: (refresh: boolean) => post<Brief>(`/ai/brief/${encodeURIComponent(id)}${refresh ? '?refresh=true' : ''}`) })
  const b = m.data
  return (
    <div className="card">
      <div className="card-head">
        <h3>Inspection brief</h3>
        <button className="btn btn-primary btn-sm" disabled={m.isPending} onClick={() => m.mutate(!!b)}>
          {m.isPending ? 'Writing…' : b ? 'Write again' : 'Write inspection brief'}
        </button>
      </div>
      {!b && !m.isPending && !m.isError && (
        <p className="muted small">Likely cause, the evidence behind it, what to check on site and a safety note, written from this meter's data.</p>
      )}
      {m.isError && <ErrorBox error={m.error} />}
      {b && (
        <div className="stack" style={{ gap: '0.8rem' }}>
          <div>
            <div className="eyebrow">Likely cause · {b.confidence} confidence</div>
            <h3 style={{ fontSize: '1.4rem' }}>{b.cause_name}</h3>
          </div>
          <p>{b.summary}</p>
          <div>
            <b className="small">Evidence</b>
            <ul className="small" style={{ margin: '0.3rem 0 0', paddingLeft: '1.2rem' }}>{b.evidence.map((e, i) => <li key={i}>{e}</li>)}</ul>
          </div>
          <div>
            <b className="small">Check on site</b>
            <ol className="small" style={{ margin: '0.3rem 0 0', paddingLeft: '1.2rem' }}>{b.field_checks.map((e, i) => <li key={i}>{e}</li>)}</ol>
          </div>
          <div className="notice warn small">{b.safety_note}</div>
          <ModeNote mode={b.mode} provider={b.provider} model={b.model} fallback={b.fallback_reason} latency={b.latency_ms} />
          <Trace steps={b.steps} />
        </div>
      )}
    </div>
  )
}

function FeedbackCard({ m }: { m: MeterDetail }) {
  const fb = useFeedback()
  const [found, setFound] = useState<'yes' | 'no' | ''>('')
  const [observed, setObserved] = useState('')
  const [notes, setNotes] = useState('')
  if (m.status !== 'pending' && !fb.isSuccess) {
    return <div className="card"><div className="card-head"><h3>Inspection outcome</h3></div><StatusTag status={m.status} /></div>
  }
  return (
    <form className="card stack" style={{ gap: '0.8rem', alignContent: 'start' }} onSubmit={(e) => {
      e.preventDefault()
      if (!found) return
      fb.mutate({ meter_id: m.meter_id, was_anomaly: found === 'yes', notes: notes || undefined,
        actual_kwh_observed: observed ? Number(observed) : null })
    }}>
      <div className="card-head" style={{ marginBottom: 0 }}><h3>Record the inspection</h3></div>
      {fb.isSuccess ? <div className="notice">{fb.data.message}</div> : (
        <>
          <fieldset className="row" style={{ border: 0, padding: 0, margin: 0 }}>
            <legend className="small" style={{ fontWeight: 600, marginBottom: '0.3rem' }}>What did the inspector find?</legend>
            <label className="row" style={{ gap: '0.3rem' }}><input type="radio" name="found" checked={found === 'yes'} onChange={() => setFound('yes')} /> Theft or tampering</label>
            <label className="row" style={{ gap: '0.3rem' }}><input type="radio" name="found" checked={found === 'no'} onChange={() => setFound('no')} /> Nothing wrong</label>
          </fieldset>
          <label className="field"><span>Load observed on site, kWh/day (optional)</span>
            <input className="input" type="number" min={0} step="0.1" value={observed} onChange={(e) => setObserved(e.target.value)} />
          </label>
          <label className="field"><span>Notes (optional)</span>
            <textarea className="textarea" maxLength={1000} value={notes} onChange={(e) => setNotes(e.target.value)} />
          </label>
          {fb.isError && <ErrorBox error={fb.error} />}
          <div><button className="btn btn-primary" disabled={!found || fb.isPending}>{fb.isPending ? 'Saving…' : 'Save outcome'}</button></div>
        </>
      )}
    </form>
  )
}

function BalanceChart({ dt }: { dt: string }) {
  const bal = useBalance(30)
  const rows = (bal.data ?? []).filter((r) => r.dt_id === dt)
    .map((r) => ({ date: r.date, metered: r.kwh_metered, unmetered: Math.max(0, r.kwh_in - r.kwh_metered), pct: r.unmetered_pct, input: r.kwh_in }))
  return (
    <div className="card">
      <div className="card-head">
        <h3>{dt}: energy in vs energy billed</h3>
        <p>kWh per day; the bar's full height is what entered the transformer</p>
      </div>
      <div className="legend">
        <span><i className="box" style={{ background: C.peers }} />Recorded by meters</span>
        <span><i className="box" style={{ background: C.gap }} />Not recorded by any meter</span>
      </div>
      {bal.isLoading ? <Loading /> : (
        <div className="chart chart-sm">
          <ResponsiveContainer>
            <BarChart data={rows} margin={{ top: 8, right: 8, bottom: 0, left: -12 }} barCategoryGap={2}>
              <CartesianGrid stroke={C.grid} vertical={false} />
              <XAxis dataKey="date" tickFormatter={shortDate} minTickGap={36} {...axisProps} />
              <YAxis {...axisProps} width={52} />
              <Tooltip cursor={{ fill: 'rgba(20,32,48,0.05)' }} content={({ active, payload, label }) => active && payload?.length ? (
                <ChartTip title={shortDate(String(label))} rows={[
                  { name: 'Entered transformer', value: kwh(payload[0].payload.input) },
                  { name: 'Recorded', value: kwh(payload[0].payload.metered), color: C.peers },
                  { name: 'Not recorded', value: `${kwh(payload[0].payload.unmetered)} (${payload[0].payload.pct.toFixed(1)}%)`, color: C.gap },
                ]} />) : null} />
              <Bar dataKey="metered" stackId="a" fill={C.peers} isAnimationActive={false} />
              <Bar dataKey="unmetered" stackId="a" fill={C.gap} radius={[3, 3, 0, 0]} isAnimationActive={false} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}
    </div>
  )
}

function Peers({ m }: { m: MeterDetail }) {
  const all = useMeters()
  const peers = (all.data ?? []).filter((x) => m.peers.includes(x.meter_id))
  return (
    <div className="card">
      <div className="card-head"><h3>Others on {m.dt_id}</h3></div>
      <div className="stack" style={{ gap: '0.5rem' }}>
        {peers.map((p) => (
          <div key={p.meter_id} className="spread small">
            <Link to={`/app/meters/${p.meter_id}`} className="mono">{p.meter_id}</Link>
            <span className="row" style={{ gap: '0.4rem' }}>
              <span className="muted">{p.category}</span><TierTag tier={p.tier} />
            </span>
          </div>
        ))}
      </div>
    </div>
  )
}

export default function Meter() {
  const { id = '' } = useParams()
  const q = useMeter(id.toUpperCase())
  if (q.isLoading) return <Loading />
  if (q.isError) {
    const notFound = q.error instanceof ApiError && q.error.status === 404
    return (
      <>
        <PageHead title={id.toUpperCase()} />
        <ErrorBox error={q.error} retry={notFound ? undefined : () => q.refetch()} />
        <p style={{ marginTop: '1rem' }}><Link to="/app/queue">Back to the inspection queue</Link></p>
      </>
    )
  }
  const m = q.data!
  const fired = m.layers.filter((l) => l.fired).length
  const verdict = m.flagged
    ? `Usage is ${Math.round(m.drop_pct)}% below this meter's own baseline, and ${fired} of 4 checks agree it is unusual.`
    : m.drop_pct > 5
      ? `Usage is ${Math.round(m.drop_pct)}% below baseline, but the checks don't agree strongly enough to flag it.`
      : 'Consumption looks normal for this meter.'
  return (
    <>
      <p className="small" style={{ marginBottom: '0.4rem' }}><Link to="/app/queue">← Inspection queue</Link></p>
      <PageHead title={m.meter_id} sub={`${m.zone} · ${m.place} · transformer ${m.dt_id} · ${m.category} customer`}>
        <TierTag tier={m.tier} />
      </PageHead>
      <div className="stack">
        <div className="notice" style={{ borderLeftColor: m.flagged ? 'var(--t-high)' : 'var(--t-normal)' }}>
          <b>{verdict}</b> {m.flagged && <span className="muted">Pattern: {PATTERN_LABEL[m.pattern].toLowerCase()}.</span>}
        </div>
        <div className="kpis">
          <Kpi label="Confidence" value={`${Math.round(m.confidence * 100)}%`} note={m.flagged ? 'flag threshold is 50%' : 'below the 50% flag threshold'} />
          <Kpi label="Usage, kWh/day" value={<span className="num">{m.baseline_kwh.toFixed(0)} → {m.recent_kwh.toFixed(0)}</span>} note="baseline → last 7 days" />
          <Kpi accent label="Estimated monthly loss" value={inr(m.est_monthly_loss_inr)} note="drop × 30 days × tariff × confidence" />
          <Kpi label="Inspection" value={<span style={{ fontSize: '1.3rem' }}><StatusTag status={m.status} /></span>} note={`scored on ${shortDate(m.date)}`} />
        </div>
        <UsageChart m={m} />
        <div>
          <h3 style={{ marginBottom: '0.7rem' }}>Evidence from each check</h3>
          <div className="grid grid-2">{m.layers.map((l) => <LayerCard key={l.name} l={l} />)}</div>
        </div>
        <div className="grid grid-2">
          <BriefCard id={m.meter_id} />
          <div className="stack">
            <FeedbackCard m={m} />
            <Peers m={m} />
          </div>
        </div>
        <BalanceChart dt={m.dt_id} />
      </div>
    </>
  )
}
