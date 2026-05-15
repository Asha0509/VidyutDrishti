import type { Step } from '../lib/types'

export default function Trace({ steps }: { steps: Step[] }) {
  if (!steps?.length) return null
  return (
    <details className="trace">
      <summary>How this answer was produced ({steps.length} step{steps.length > 1 ? 's' : ''})</summary>
      <ol>
        {steps.map((s, i) => (
          <li key={i}>
            <b>{s.kind === 'tool' ? `Looked up ${s.name.replace(/_/g, ' ')}` : s.kind === 'llm' ? 'Asked the model' : s.name}</b>
            {s.args && Object.keys(s.args).length > 0 && <span className="mono muted"> {JSON.stringify(s.args)}</span>}
            {s.summary && <span className="muted"> · {s.summary}</span>}
            {s.model && <span className="mono muted"> · {s.provider}/{s.model}</span>}
            {s.failovers?.length ? <span className="muted"> · failed over from {s.failovers.join(', ')}</span> : null}
            {s.ms != null && <span className="muted num"> · {Math.round(s.ms)} ms</span>}
          </li>
        ))}
      </ol>
    </details>
  )
}
