import { useQuery } from '@tanstack/react-query'
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { get } from '../api'
import { ChartTip, ErrorBox, Kpi, Loading, PageHead } from '../components/ui'
import { pct } from '../lib/format'
import { useAiStatus } from '../lib/queries'

interface Summary {
  window_hours: number
  llm: { calls: number; errors: number; error_rate: number | null; latency_ms_p50: number | null; latency_ms_p95: number | null
    prompt_tokens: number; completion_tokens: number; tool_calls: number; by_provider: Record<string, number>; by_purpose: Record<string, number> }
  triage: { runs: number; by_decision_path: Record<string, number>; by_label: Record<string, number>; fallback_rate: number | null
    latency_ms_p50: number | null; latency_ms_p95: number | null; avg_llm_calls: number | null }
}
interface Call { ts: number; purpose: string; provider: string; model: string; status: string; error: string | null; latency_ms: number; prompt_tokens: number; completion_tokens: number; tool_calls: number }
interface Run { ts: number; decision_path: string; label: string; fallback_reason: string | null; latency_ms: number; llm_calls: number; tool_calls: number; source: string }
interface Point { ts: number; calls: number; errors: number; latency_ms_p50: number | null }

const FEATURE: Record<string, string> = { copilot: 'Copilot', brief: 'Inspection brief', digest: 'Alert digest', inspection_brief: 'Inspection brief', alert_digest: 'Alert digest' }
const ms = (v: number | null | undefined) => (v == null ? '–' : v < 1000 ? `${Math.round(v)} ms` : `${(v / 1000).toFixed(1)} s`)
const when = (ts: number) => new Date(ts * 1000).toLocaleString('en-IN', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' })

export default function Ops() {
  const status = useAiStatus()
  const sum = useQuery({ queryKey: ['ops-summary'], queryFn: () => get<Summary>('/ai/ops/summary?hours=168'), refetchInterval: 30_000 })
  const runs = useQuery({ queryKey: ['ops-runs'], queryFn: () => get<{ runs: Run[] }>('/ai/ops/runs?limit=25'), refetchInterval: 30_000 })
  const calls = useQuery({ queryKey: ['ops-calls'], queryFn: () => get<{ calls: Call[] }>('/ai/ops/calls?limit=25'), refetchInterval: 30_000 })
  const ts = useQuery({ queryKey: ['ops-ts'], queryFn: () => get<{ points: Point[] }>('/ai/ops/timeseries?hours=24&bucket_minutes=60') })
  const s = sum.data

  return (
    <>
      <PageHead title="AI operations"
        sub="Every AI request this server has handled in the last 7 days: which path answered it, how long it took, and every model call behind it." />
      {status.data && (
        <div className="notice" style={{ marginBottom: '1rem' }}>
          {status.data.agent_enabled
            ? <>AI model configured: {Object.entries(status.data.llm_models).map(([p, m]) => `${p} (${m})`).join(', ')}. Providers are tried in order; if all fail, the rule-based path answers. {status.data.rate_limit}.</>
            : <>No AI model is configured, so every request is answered by the rule-based path. Model calls will appear here once a key is set.</>}
        </div>
      )}
      {sum.isLoading && <Loading />}
      {sum.isError && <ErrorBox error={sum.error} retry={() => sum.refetch()} />}
      {s && (
        <div className="stack">
          <div className="kpis">
            <Kpi label="AI requests" value={s.triage.runs} note={Object.entries(s.triage.by_label).map(([k, v]) => `${FEATURE[k] ?? k} ${v}`).join(' · ') || 'none yet'} />
            <Kpi label="Answered by rules" value={s.triage.fallback_rate == null ? '–' : pct(s.triage.fallback_rate)} note="model missing or failed" />
            <Kpi label="Response time" value={ms(s.triage.latency_ms_p50)} note={`median · 95th percentile ${ms(s.triage.latency_ms_p95)}`} />
            <Kpi label="Model calls" value={s.llm.calls} note={`${s.llm.errors} failed${s.llm.error_rate != null ? ` (${pct(s.llm.error_rate)})` : ''} · ${s.llm.tool_calls} tool calls`} />
            <Kpi label="Tokens" value={(s.llm.prompt_tokens + s.llm.completion_tokens).toLocaleString('en-IN')} note={`${s.llm.prompt_tokens.toLocaleString('en-IN')} in · ${s.llm.completion_tokens.toLocaleString('en-IN')} out`} />
          </div>

          <div className="card">
            <div className="card-head"><h3>Model calls, last 24 hours</h3><p>per hour</p></div>
            {ts.data && ts.data.points.length > 0 ? (
              <div className="chart chart-sm">
                <ResponsiveContainer>
                  <BarChart data={ts.data.points} margin={{ top: 8, right: 8, bottom: 0, left: -20 }}>
                    <CartesianGrid stroke="#E3E8EE" vertical={false} />
                    <XAxis dataKey="ts" tickFormatter={(t) => new Date(t * 1000).toTimeString().slice(0, 5)} tick={{ fontSize: 12, fill: '#5d6b7c' }} tickLine={false} />
                    <YAxis allowDecimals={false} tick={{ fontSize: 12, fill: '#5d6b7c' }} tickLine={false} axisLine={false} width={40} />
                    <Tooltip cursor={{ fill: 'rgba(20,32,48,0.05)' }} content={({ active, payload }) => active && payload?.length ? (
                      <ChartTip title={when(payload[0].payload.ts)} rows={[
                        { name: 'Calls', value: String(payload[0].payload.calls), color: '#2F6DB5' },
                        { name: 'Failed', value: String(payload[0].payload.errors) },
                        { name: 'Median latency', value: ms(payload[0].payload.latency_ms_p50) },
                      ]} />) : null} />
                    <Bar dataKey="calls" fill="#2F6DB5" radius={[3, 3, 0, 0]} isAnimationActive={false} />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            ) : <p className="muted">No model calls in the last 24 hours.</p>}
          </div>

          <div className="grid grid-2">
            <div className="card">
              <div className="card-head"><h3>Recent requests</h3></div>
              {runs.isError ? <ErrorBox error={runs.error} /> : (
                <div className="table-wrap">
                  <table className="data small">
                    <thead><tr><th>When</th><th>Feature</th><th>Answered by</th><th className="r">Time</th><th className="r">Tools</th></tr></thead>
                    <tbody>
                      {runs.data?.runs.map((r, i) => (
                        <tr key={i}>
                          <td className="num">{when(r.ts)}</td>
                          <td>{FEATURE[r.label] ?? r.label}</td>
                          <td>{r.decision_path === 'agent' ? `Model (${r.llm_calls} call${r.llm_calls === 1 ? '' : 's'})` : 'Rules'}</td>
                          <td className="r">{ms(r.latency_ms)}</td>
                          <td className="r">{r.tool_calls}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                  {runs.data?.runs.length === 0 && <p className="muted">Nothing yet.</p>}
                </div>
              )}
            </div>
            <div className="card">
              <div className="card-head"><h3>Recent model calls</h3></div>
              {calls.isError ? <ErrorBox error={calls.error} /> : calls.data?.calls.length ? (
                <div className="table-wrap">
                  <table className="data small">
                    <thead><tr><th>When</th><th>Feature</th><th>Model</th><th>Result</th><th className="r">Time</th><th className="r">Tokens</th></tr></thead>
                    <tbody>
                      {calls.data.calls.map((c, i) => (
                        <tr key={i}>
                          <td className="num">{when(c.ts)}</td>
                          <td>{FEATURE[c.purpose] ?? c.purpose}</td>
                          <td className="mono">{c.provider}/{c.model}</td>
                          <td>{c.status === 'ok' ? 'OK' : <span title={c.error ?? ''} style={{ color: 'var(--t-high)' }}>Failed</span>}</td>
                          <td className="r">{ms(c.latency_ms)}</td>
                          <td className="r">{(c.prompt_tokens ?? 0) + (c.completion_tokens ?? 0)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : <p className="muted">No model calls recorded.</p>}
            </div>
          </div>
        </div>
      )}
    </>
  )
}
