import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { get } from '../api'
import DTDiagram from '../components/DTDiagram'
import { BrandMark } from '../components/ui'
import { latestBalance, useBalance, useMeters, useZones } from '../lib/queries'
import type { MeterSummary } from '../lib/types'

const LAYERS = [
  { code: 'L0', title: 'Transformer balance', body: 'Energy into each transformer is compared with what its meters recorded. When the unrecorded share jumps, the meters whose drop explains the gap are singled out.' },
  { code: 'L1', title: 'Own history', body: "Each meter's last week is compared with its own previous two weeks, with a separate trend test that catches slow, step-by-step tampering." },
  { code: 'L2', title: 'Neighbours', body: 'A meter that falls while the other customers on the same transformer stay steady is suspicious. One that falls with them is probably weather or a holiday.' },
  { code: 'L3', title: 'Outlier model', body: 'An isolation forest looks for consumption shapes unlike the rest of the network. It only adds weight; it never flags a meter on its own.' },
]

// Shown if the API is asleep, so the page never opens on an empty panel.
const EXAMPLE: MeterSummary[] = [
  ['M01', 'NORMAL', 0], ['M02', 'NORMAL', 0], ['M03', 'HIGH', 95], ['M04', 'NORMAL', 0], ['M05', 'MEDIUM', 41], ['M06', 'HIGH', 100],
].map(([s, tier, drop]) => ({ meter_id: `DT1-${s}`, dt_id: 'DT1', zone: 'ZoneA', category: 'domestic', confidence: 0, tier: tier as MeterSummary['tier'], pattern: 'normal', drop_pct: drop as number, flagged: tier !== 'NORMAL' }))

interface HeldOut { networks: number; precision: { mean: number }; recall: { mean: number }; f1_score: { mean: number }; decoys_flagged_rate: number; by_theft_kind: Record<string, { recall: number }> }
interface Eval { demo: { detection_lag_days?: { mean: number | null } } | null; held_out: HeldOut | null }

function HeroDiagram() {
  const meters = useMeters()
  const bal = useBalance(7)
  const zones = useZones()
  const latest = latestBalance(bal.data)
  const worst = Object.values(latest).sort((a, b) => b.unmetered_pct - a.unmetered_pct)[0]
  const live = meters.data && worst
  const dt = live ? worst.dt_id : 'DT1'
  const place = zones.data?.find((z) => z.dt_id === dt)?.place
  return (
    <div className="hero-panel">
      <DTDiagram dark dtId={dt} linkable={!!live}
        meters={live ? meters.data!.filter((m) => m.dt_id === dt) : EXAMPLE}
        kwhIn={live ? worst.kwh_in : 348} unmeteredPct={live ? worst.unmetered_pct : 77} />
      <div className="cap">
        <span>{live ? `Live from the demo network: ${dt}${place ? `, ${place}` : ''}` : 'Example transformer (connecting to the demo server…)'}</span>
        {live && <span>Select a meter to see why</span>}
      </div>
    </div>
  )
}

function Stat({ value, label }: { value: string; label: string }) {
  return <div className="stat"><b>{value}</b><span>{label}</span></div>
}

function Accuracy() {
  const ev = useQuery({ queryKey: ['evaluation'], queryFn: () => get<Eval>('/metrics/evaluation') })
  const h = ev.data?.held_out
  const p = (v?: number) => (v == null ? '…' : `${Math.round(v * 100)}%`)
  const lag = ev.data?.demo?.detection_lag_days?.mean
  return (
    <>
      <div className="stats">
        <Stat value={p(h?.precision.mean)} label="of flagged meters were real thefts (precision)" />
        <Stat value={p(h?.recall.mean)} label="of thefts were flagged (recall)" />
        <Stat value={lag == null ? '…' : `${lag} days`} label="average time from theft starting to first flag (demo network)" />
        <Stat value={p(h?.by_theft_kind?.gradual_tampering?.recall)} label="of slow, gradual tampering caught, the hardest case" />
      </div>
      <p className="muted small" style={{ marginTop: '0.8rem' }}>
        {h ? `Mean over ${h.networks} randomly generated networks that were never used while tuning the thresholds. ` : ''}
        Vacant houses look like theft at first: {h ? p(h.decoys_flagged_rate) : 'about half'} of them are still flagged, which is why every
        flag comes with an inspection brief and a field check before anyone is accused.{' '}
        <Link to="/app/quality">Full results, threshold sweep and ROI</Link>
      </p>
    </>
  )
}

export default function Landing() {
  return (
    <div className="landing">
      <header className="l-nav">
        <Link to="/" className="brand"><BrandMark /><span className="brand-name">VidyutDrishti</span></Link>
        <nav className="links" aria-label="Page">
          <a className="hide-sm" href="#how">How it works</a>
          <a className="hide-sm" href="#accuracy">Accuracy</a>
          <a className="hide-sm" href="#ai">AI features</a>
          <Link className="btn btn-signal btn-sm" to="/app">Open the control room</Link>
        </nav>
      </header>

      <section className="hero">
        <div className="hero-grid">
          <div>
            <div className="eyebrow" style={{ color: '#9fb0c2' }}>Electricity theft detection for distribution networks</div>
            <h1 style={{ marginTop: '0.6rem' }}>Find the meter that's hiding the <em>missing energy</em>.</h1>
            <p className="lede">
              VidyutDrishti compares what each transformer sends out with what its customers' meters record, then checks every meter
              against its own history and its neighbours. Inspectors get a list ranked by rupees at stake, with the evidence for each call.
            </p>
            <div className="row">
              <Link className="btn btn-signal" to="/app">Open the control room</Link>
              <Link className="btn btn-outline-light" to="/app/queue">See today's inspection list</Link>
            </div>
          </div>
          <HeroDiagram />
        </div>
      </section>

      <section className="section" id="how">
        <div className="section-head">
          <div className="eyebrow">How it decides</div>
          <h2>Four independent checks, one ranked list</h2>
          <p>
            No single signal is trusted alone. A meter is flagged when the checks agree, and the queue is ordered by expected
            recoverable money: confidence × the size of the drop × the customer's tariff.
          </p>
        </div>
        <div className="steps">
          {LAYERS.map((l) => (
            <div className="step" key={l.code}>
              <span className="code">{l.code}</span>
              <h3>{l.title}</h3>
              <p className="muted">{l.body}</p>
            </div>
          ))}
        </div>
      </section>

      <div className="band">
        <section className="section" id="accuracy">
          <div className="section-head">
            <div className="eyebrow">Measured, not claimed</div>
            <h2>Accuracy on networks it has never seen</h2>
            <p>The simulator records every theft it injects, so each flag can be checked meter by meter.</p>
          </div>
          <Accuracy />
        </section>
      </div>

      <section className="section" id="ai">
        <div className="section-head">
          <div className="eyebrow">AI where it helps</div>
          <h2>Language models explain and summarise. They don't decide.</h2>
          <p>
            Detection is deterministic and testable. The AI features sit on top: every number they mention comes from a data tool,
            and if the model is unavailable a rule-based answer is used and labelled as such.
          </p>
        </div>
        <div className="grid grid-3">
          <div className="step">
            <h3>Ask the data</h3>
            <p className="muted">"Which zone is losing the most?" The copilot calls the same data tools the dashboard uses and shows each step.</p>
            <Link to="/app/copilot">Try the copilot</Link>
          </div>
          <div className="step">
            <h3>Inspection brief</h3>
            <p className="muted">For any flagged meter: the likely cause, the evidence, what to check on site and a safety note for the field team.</p>
            <Link to="/app/queue">Open a meter</Link>
          </div>
          <div className="step">
            <h3>Morning digest</h3>
            <p className="muted">New flags, escalations and transformer balance jumps, de-duplicated and summarised into what needs action today.</p>
            <Link to="/app/alerts">See alerts</Link>
          </div>
        </div>
      </section>

      <div className="band">
        <section className="section">
          <div className="section-head">
            <div className="eyebrow">Read before quoting</div>
            <h2>What this demo is and isn't</h2>
          </div>
          <div className="honest">
            <ul>
              <li>All data comes from a simulator: 8 transformers, 48 meters, 60 days of 15-minute readings, with known thefts and vacant-house decoys.</li>
              <li>Thresholds were tuned on development networks only; the numbers above are from separate held-out networks.</li>
            </ul>
            <ul>
              <li>Rupee figures use flat assumed tariffs (₹6 domestic, ₹8 industrial, ₹9 commercial per kWh) and are estimates.</li>
              <li>The demo keeps data in memory. The Docker setup adds TimescaleDB for ingestion and forecasts.</li>
            </ul>
          </div>
        </section>
      </div>

      <footer className="l-foot">
        <div className="spread">
          <span>VidyutDrishti · AT&amp;C loss detection demo</span>
          <span><a href="https://github.com/Asha0509/vidyutdrishti" target="_blank" rel="noreferrer">Source on GitHub</a></span>
        </div>
      </footer>
    </div>
  )
}
