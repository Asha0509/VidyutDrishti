import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { CartesianGrid, Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { get } from '../api'
import { ChartTip, ErrorBox, Kpi, Loading, PageHead } from '../components/ui'
import { inr, pct } from '../lib/format'

interface Range { mean: number; min: number; max: number }
interface Sweep { threshold: number; precision: number; recall: number; f1: number; flagged?: number }
interface HeldOut {
  run_at: string; networks: number; setup: string; precision: Range; recall: Range; f1_score: Range; precision_at_10: Range
  decoys_flagged_rate: number; by_theft_kind: Record<string, { meters: number; caught: number; recall: number; pattern_accuracy: number }>
  threshold_sweep: Sweep[]
}
interface Demo {
  threshold: number; meters: number; theft_meters: number; decoy_meters: number; true_positives: number; false_positives: number
  false_negatives: number; true_negatives: number; precision: number; recall: number; f1_score: number; precision_at_10: number | null
  decoys_flagged: string[]; missed_thefts: string[]; field_feedback: { confirmed: number; dismissed: number }
  detection_lag_days: { per_meter: Record<string, number | null>; mean: number | null; step_days: number } | null
}
interface AiEvalPart { brief: { cases: number; cause_accuracy: number; theft_vs_genuine_accuracy: number; by_truth: Record<string, { n: number; accuracy: number }>; fallbacks: number | null }
  copilot: { cases: number; pass_rate: number; hallucinated_answers: number; latency_ms_p50: number | null }
  run_at: string; networks: number[]; providers: string[]; copilot_failures: { question: string; expected: string[]; answer: string }[] }
interface ROI {
  bescom_consumers: number; detection_rate: number; avg_monthly_theft_inr: number; monthly_recovery_inr: number; annual_recovery_inr: number
  payback_months: number; five_year_npv_cr: number; assumptions: string[]
}

const KIND: Record<string, string> = {
  hook_bypass: 'Hook / bypass (sudden drop)', meter_stop: 'Meter stopped', gradual_tampering: 'Gradual tampering',
  vacancy: 'Vacant house (not theft)', false_alarm: 'False alarm (not theft)',
}
const range = (r: Range) => `range ${pct(r.min)}–${pct(r.max)}`

function SweepChart({ rows, current }: { rows: Sweep[]; current: number }) {
  return (
    <>
      <div className="legend">
        <span><i style={{ background: '#2F6DB5' }} />Precision: flagged meters that were thefts</span>
        <span><i style={{ background: '#14917A' }} />Recall: thefts that were flagged</span>
      </div>
      <div className="chart chart-sm">
        <ResponsiveContainer>
          <LineChart data={rows} margin={{ top: 18, right: 16, bottom: 0, left: 0 }}>
            <CartesianGrid stroke="#E3E8EE" vertical={false} />
            <XAxis dataKey="threshold" tick={{ fontSize: 12, fill: '#5d6b7c' }} tickLine={false} />
            <YAxis domain={[0, 1]} tickFormatter={(v) => `${v * 100}%`} tick={{ fontSize: 12, fill: '#5d6b7c' }} tickLine={false} axisLine={false} width={44} />
            <ReferenceLine x={current} stroke="#142030" strokeDasharray="4 4" label={{ value: 'in use', position: 'top', fontSize: 12, fill: '#142030' }} />
            <Tooltip content={({ active, payload, label }) => active && payload?.length ? (
              <ChartTip title={`Flag at confidence ≥ ${label}`} rows={[
                { name: 'Precision', value: pct(payload[0].payload.precision), color: '#2F6DB5' },
                { name: 'Recall', value: pct(payload[0].payload.recall), color: '#14917A' },
                { name: 'F1', value: payload[0].payload.f1.toFixed(2) },
              ]} />) : null} />
            <Line dataKey="precision" stroke="#2F6DB5" strokeWidth={2} dot={{ r: 4 }} isAnimationActive={false} />
            <Line dataKey="recall" stroke="#14917A" strokeWidth={2} dot={{ r: 4 }} isAnimationActive={false} />
          </LineChart>
        </ResponsiveContainer>
      </div>
    </>
  )
}

function HeldOutCard({ h, threshold }: { h: HeldOut; threshold: number }) {
  return (
    <div className="card">
      <div className="card-head">
        <h3>Held-out networks: the numbers to quote</h3>
        <p>{h.networks} networks never used for tuning · {h.setup}</p>
      </div>
      <div className="kpis" style={{ marginBottom: '1.2rem' }}>
        <Kpi accent label="Precision" value={pct(h.precision.mean)} note={range(h.precision)} />
        <Kpi accent label="Recall" value={pct(h.recall.mean)} note={range(h.recall)} />
        <Kpi label="F1 score" value={h.f1_score.mean.toFixed(2)} note={`range ${h.f1_score.min.toFixed(2)}–${h.f1_score.max.toFixed(2)}`} />
        <Kpi label="Top-10 precision" value={pct(h.precision_at_10.mean)} note="of the first 10 meters in the queue" />
        <Kpi label="Vacant houses flagged" value={pct(h.decoys_flagged_rate)} note="the main false-alarm source" />
      </div>
      <div className="grid grid-2">
        <div>
          <h4 style={{ marginBottom: '0.5rem' }}>By kind of theft</h4>
          <div className="table-wrap">
            <table className="data">
              <thead><tr><th>Kind</th><th className="r">Meters</th><th className="r">Caught</th><th className="r">Named correctly</th></tr></thead>
              <tbody>
                {Object.entries(h.by_theft_kind).map(([k, v]) => (
                  <tr key={k}><td>{KIND[k] ?? k}</td><td className="r">{v.meters}</td><td className="r">{pct(v.recall)}</td><td className="r">{pct(v.pattern_accuracy)}</td></tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="small muted" style={{ marginTop: '0.5rem' }}>
            "Named correctly" is whether the detector's pattern label matches the theft. Gradual tampering is usually caught, but rarely labelled as a gradual decline.
          </p>
        </div>
        <div>
          <h4 style={{ marginBottom: '0.5rem' }}>Trading precision for recall</h4>
          <SweepChart rows={h.threshold_sweep} current={threshold} />
        </div>
      </div>
    </div>
  )
}

function DemoCard({ d }: { d: Demo }) {
  const lag = d.detection_lag_days
  return (
    <div className="card">
      <div className="card-head">
        <h3>This demo network</h3>
        <p>Scored against the simulator's own record of thefts. Thresholds were developed on networks like this one, so read it as optimistic.</p>
      </div>
      <div className="grid grid-2">
        <div className="table-wrap">
          <table className="data">
            <thead><tr><th></th><th className="r">Was theft</th><th className="r">Wasn't theft</th></tr></thead>
            <tbody>
              <tr><td><b>Flagged</b></td><td className="r">{d.true_positives}</td><td className="r">{d.false_positives}</td></tr>
              <tr><td><b>Not flagged</b></td><td className="r">{d.false_negatives}</td><td className="r">{d.true_negatives}</td></tr>
            </tbody>
          </table>
          <p className="small muted" style={{ marginTop: '0.6rem' }}>
            Precision {pct(d.precision)}, recall {pct(d.recall)}, F1 {d.f1_score.toFixed(2)} on {d.meters} meters
            ({d.theft_meters} thefts, {d.decoy_meters} vacant-house decoys).
          </p>
        </div>
        <div className="stack small" style={{ gap: '0.6rem' }}>
          <div><b>False alarms: </b>{d.decoys_flagged.length ? d.decoys_flagged.map((m, i) => <span key={m}>{i > 0 && ', '}<Link className="mono" to={`/app/meters/${m}`}>{m}</Link></span>) : 'none'}
            {d.decoys_flagged.length > 0 && <span className="muted"> (vacant houses)</span>}</div>
          <div><b>Missed thefts: </b>{d.missed_thefts.length ? d.missed_thefts.join(', ') : 'none'}</div>
          {lag && <div><b>Days from theft starting to first flag: </b>{lag.mean} on average (checked every {lag.step_days} days)</div>}
          <div><b>Field outcomes recorded: </b>{d.field_feedback.confirmed} theft confirmed, {d.field_feedback.dismissed} nothing found</div>
        </div>
      </div>
    </div>
  )
}

function AiEvalCard() {
  const ev = useQuery({ queryKey: ['ai-evals'], queryFn: () => get<Record<string, AiEvalPart>>('/ai/evals') })
  const modes = Object.entries(ev.data ?? {})
  return (
    <div className="card">
      <div className="card-head">
        <h3>AI features, evaluated</h3>
        <p>evals/ai_eval.py on unseen networks: brief causes checked against the simulator, copilot answers against computed values</p>
      </div>
      {ev.isLoading && <Loading />}
      {ev.isError && <ErrorBox error={ev.error} />}
      {!ev.data?.agent && ev.data && (
        <div className="notice warn small" style={{ marginBottom: '1rem' }}>
          Only the rule-based baseline has been run so far. The AI model's results appear here once the eval is run with a model key.
        </div>
      )}
      <div className="grid grid-2">
        {modes.map(([mode, r]) => (
          <div key={mode} className="stack" style={{ gap: '0.7rem' }}>
            <h4>{mode === 'agent' ? `AI model (${r.providers.join(', ')})` : 'Rule-based baseline'}</h4>
            <div className="kpis">
              <Kpi label="Brief: cause right" value={pct(r.brief.cause_accuracy)} note={`${r.brief.cases} meters`} />
              <Kpi label="Brief: theft vs not" value={pct(r.brief.theft_vs_genuine_accuracy)} note="the call that matters in the field" />
              <Kpi label="Copilot answers right" value={pct(r.copilot.pass_rate)} note={`${r.copilot.cases} questions · ${r.copilot.hallucinated_answers} invented a meter`} />
            </div>
            <table className="data small">
              <thead><tr><th>True cause</th><th className="r">Meters</th><th className="r">Brief right</th></tr></thead>
              <tbody>{Object.entries(r.brief.by_truth).map(([k, v]) => (
                <tr key={k}><td>{KIND[k] ?? k}</td><td className="r">{v.n}</td><td className="r">{pct(v.accuracy)}</td></tr>
              ))}</tbody>
            </table>
            {r.copilot_failures.length > 0 && (
              <details className="trace">
                <summary>Questions it got wrong ({r.copilot_failures.length} shown)</summary>
                <ul style={{ paddingLeft: '1.2rem' }}>{r.copilot_failures.map((f, i) => (
                  <li key={i}><b>{f.question}</b> <span className="muted">expected {f.expected.join(', ')}; answered: "{f.answer.slice(0, 140)}{f.answer.length > 140 ? '…' : ''}"</span></li>
                ))}</ul>
              </details>
            )}
            <p className="small muted">Run {new Date(r.run_at).toLocaleString('en-IN')} on networks {r.networks.join(', ')}</p>
          </div>
        ))}
      </div>
    </div>
  )
}

function RoiCard({ recall }: { recall: number }) {
  const [rate, setRate] = useState(Math.round(recall * 100))
  const [theft, setTheft] = useState(3500)
  const roi = useQuery({
    queryKey: ['roi', rate, theft],
    queryFn: () => get<ROI>(`/metrics/roi?detection_rate=${rate / 100}&avg_monthly_theft_inr=${theft}`),
    placeholderData: (prev) => prev,
  })
  const r = roi.data
  const cr = (v: number) => `₹${(v / 1e7).toFixed(1)} crore`
  return (
    <div className="card">
      <div className="card-head">
        <h3>What it could be worth at utility scale</h3>
        <p>Illustrative only: every input below is an assumption, not a measurement</p>
      </div>
      <div className="grid grid-2">
        <div className="stack" style={{ gap: '1rem' }}>
          <label className="field"><span>Share of thefts caught: {rate}%</span>
            <input type="range" min={20} max={100} value={rate} onChange={(e) => setRate(Number(e.target.value))} />
            <span className="small muted">Starts at the held-out recall above.</span>
          </label>
          <label className="field"><span>Average theft per stealing customer: {inr(theft)} a month</span>
            <input type="range" min={500} max={10000} step={100} value={theft} onChange={(e) => setTheft(Number(e.target.value))} />
          </label>
          {r && <ul className="small muted" style={{ paddingLeft: '1.2rem', margin: 0 }}>{r.assumptions.map((a) => <li key={a}>{a}</li>)}</ul>}
        </div>
        {roi.isError ? <ErrorBox error={roi.error} /> : r ? (
          <div className="kpis" style={{ alignContent: 'start' }}>
            <Kpi accent label="Recovered a year" value={cr(r.annual_recovery_inr)} note={`${cr(r.monthly_recovery_inr)} a month`} />
            <Kpi label="Payback" value={r.payback_months < 1 ? `${Math.max(1, Math.round(r.payback_months * 30))} days` : `${r.payback_months.toFixed(1)} months`} note="on the assumed ₹15 crore platform cost" />
            <Kpi label="5-year net present value" value={`₹${Math.round(r.five_year_npv_cr).toLocaleString('en-IN')} crore`} note="at a 10% discount rate" />
          </div>
        ) : <Loading />}
      </div>
    </div>
  )
}

export default function Quality() {
  const ev = useQuery({ queryKey: ['evaluation'], queryFn: () => get<{ demo: Demo | null; held_out: HeldOut | null }>('/metrics/evaluation') })
  return (
    <>
      <PageHead title="Accuracy & ROI"
        sub="How often the detector is right, measured against simulated ground truth, how the AI features score, and an illustrative business case." />
      {ev.isLoading && <Loading />}
      {ev.isError && <ErrorBox error={ev.error} retry={() => ev.refetch()} />}
      {ev.data && (
        <div className="stack">
          {ev.data.held_out ? <HeldOutCard h={ev.data.held_out} threshold={ev.data.demo?.threshold ?? 0.5} />
            : <div className="notice warn">The held-out evaluation hasn't been run on this server (evals/detection_eval.py).</div>}
          {ev.data.demo && <DemoCard d={ev.data.demo} />}
          <AiEvalCard />
          <RoiCard recall={ev.data.held_out?.recall.mean ?? 0.85} />
        </div>
      )}
    </>
  )
}
