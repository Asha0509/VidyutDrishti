import { useEffect, useState } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'

interface Step {
  to: string
  title: string
  what: string
  has: string[]
}

// One step per page. The text is the plain-language map of the app; the bullets
// name what is actually on the page so a first-time visitor knows where to look.
export const STEPS: Step[] = [
  {
    to: '/app',
    title: 'Overview',
    what: 'The one-screen answer to "how bad is it today and where do I send people first?"',
    has: [
      'Four headline numbers: estimated monthly loss, meters flagged, awaiting inspection, zones at risk',
      '"Inspect first": the five meters worth the most rupees, with the pattern seen',
      '"Today\'s digest": a short written summary of what changed (written by a model, with a rule-based fallback)',
      '"Unmetered energy by transformer" and "Which checks fired": where energy goes missing and which of the four checks agreed',
    ],
  },
  {
    to: '/app/queue',
    title: 'Inspection queue',
    what: 'Every flagged meter in the order a field team should visit, ranked by recoverable money.',
    has: [
      'Filters for risk, zone and inspection status',
      'Per meter: risk level and confidence, what changed (for example 193 to 0 kWh/day), which of the checks L0-L3 agreed, rupees per month',
      '"Theft found" / "Nothing found" buttons: record the visit result, which feeds the Accuracy page',
    ],
  },
  {
    to: '/app/meters/DT1-M03',
    title: 'One meter in detail',
    what: 'The evidence behind a single flag. Click any meter ID in the queue to get here.',
    has: [
      'Daily consumption chart for the meter',
      '"Evidence from each check": what each of the four checks saw',
      '"Inspection brief": likely cause and what to check on site (button writes one; model with a rule-based fallback)',
      '"Record the inspection", plus the other meters on the same transformer and the transformer\'s energy balance',
    ],
  },
  {
    to: '/app/zones',
    title: 'Zones & transformers',
    what: 'The same story one level up: which parts of the network lose the most.',
    has: [
      '"Zones by estimated loss" and a card per transformer',
      'A demand chart for a feeder: the last 24 hours and the next 24 hours forecast',
      '"All transformers" table with unmetered share',
    ],
  },
  {
    to: '/app/alerts',
    title: 'Alerts',
    what: 'A day-by-day feed of what needs attention, with a written digest on top.',
    has: [
      '"Digest for the period": new flags, escalations and balance jumps, de-duplicated',
      'One block per day listing each alert',
    ],
  },
  {
    to: '/app/copilot',
    title: 'Ask the data',
    what: 'Type a question in plain language. The assistant calls the same data tools the dashboard uses.',
    has: [
      'Suggested questions you can click',
      'Each answer shows which model wrote it, how long it took, and an expandable "How this answer was produced" listing every tool call',
      'If no model is available, a rule-based answer is used and labelled as such',
    ],
  },
  {
    to: '/app/quality',
    title: 'Accuracy & ROI',
    what: 'How good the detector is, measured on networks it was never tuned on.',
    has: [
      '"Held-out networks": precision, recall and the hardest case (slow, gradual tampering)',
      '"This demo network" and "AI features, evaluated"',
      '"What it could be worth at utility scale": an assumption-driven estimate, clearly labelled',
    ],
  },
  {
    to: '/app/ops',
    title: 'AI operations',
    what: 'The audit log for the model features: nothing happens off the record.',
    has: [
      '"Model calls, last 24 hours": counts, latency and fallbacks',
      '"Recent requests" and "Recent model calls" with provider, tokens and tool calls',
    ],
  },
]

export default function Tour({ open, onClose }: { open: boolean; onClose: () => void }) {
  const [i, setI] = useState(0)
  const nav = useNavigate()
  const loc = useLocation()
  const step = STEPS[i]

  useEffect(() => {
    if (open && loc.pathname !== step.to) nav(step.to)
    // Navigate only when the step changes or the tour opens, not on every route change.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, i])

  if (!open) return null
  return (
    <aside className="tour" role="dialog" aria-label="App tour">
      <div className="tour-head">
        <span>App tour · {i + 1} of {STEPS.length}</span>
        <button className="tour-x" onClick={onClose} aria-label="Close tour">×</button>
      </div>
      <h2>{step.title}</h2>
      <p className="tour-what">{step.what}</p>
      <ul>{step.has.map((h) => <li key={h}>{h}</li>)}</ul>
      <div className="tour-nav">
        <button className="btn btn-sm" disabled={i === 0} onClick={() => setI(i - 1)}>Back</button>
        {i < STEPS.length - 1
          ? <button className="btn btn-sm btn-primary" onClick={() => setI(i + 1)}>Next page</button>
          : <button className="btn btn-sm btn-primary" onClick={onClose}>Finish</button>}
      </div>
    </aside>
  )
}
