import { useEffect, useRef, useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import { post } from '../api'
import Trace from '../components/Trace'
import { ErrorBox, ModeNote, PageHead } from '../components/ui'
import { useAiStatus } from '../lib/queries'
import type { CopilotAnswer } from '../lib/types'

interface Turn { role: 'user' | 'assistant'; content: string; meta?: CopilotAnswer }

const STARTERS = [
  'Which zone is losing the most money?',
  'Which meters should we inspect first?',
  'Tell me about DT1-M03',
  "How is DT3's energy balance?",
  'How accurate is the detector?',
]
// Needs the model; the rule-based fallback only covers the questions above.
const AGENT_ONLY = ['What changed in the last 3 days?', 'Which gradual-decline meters are in Zone D?']

export default function Copilot() {
  const status = useAiStatus()
  const [turns, setTurns] = useState<Turn[]>([])
  const [text, setText] = useState('')
  const end = useRef<HTMLDivElement>(null)
  const ask = useMutation({
    mutationFn: (question: string) => post<CopilotAnswer>('/ai/copilot', {
      question, history: turns.slice(-8).map(({ role, content }) => ({ role, content: content.slice(0, 2000) })),
    }),
    onSuccess: (r) => setTurns((t) => [...t, { role: 'assistant', content: r.answer, meta: r }]),
  })
  useEffect(() => { end.current?.scrollIntoView({ behavior: 'smooth', block: 'end' }) }, [turns.length, ask.isPending])

  const send = (q: string) => {
    const question = q.trim()
    if (question.length < 3 || ask.isPending) return
    setTurns((t) => [...t, { role: 'user', content: question }])
    setText('')
    ask.mutate(question)
  }
  const last = [...turns].reverse().find((t) => t.meta)?.meta
  const followUps = last?.follow_ups?.length ? last.follow_ups : turns.length ? [] : status.data?.agent_enabled ? [...STARTERS, ...AGENT_ONLY] : STARTERS

  return (
    <>
      <PageHead title="Ask the data"
        sub="Questions about the network in plain language. Every number in an answer is fetched through the same data tools the dashboard uses; open the steps under an answer to see them." />
      {status.data && !status.data.agent_enabled && (
        <div className="notice warn" style={{ marginBottom: '1rem' }}>
          No AI model is configured on this server, so answers come from fixed rules and only cover common questions like the ones below.
        </div>
      )}
      <div className="chat" aria-live="polite">
        {turns.map((t, i) => (
          <div key={i} className={`msg ${t.role}`}>
            <div className="msg-text">{t.content}</div>
            {t.meta && (
              <>
                <ModeNote mode={t.meta.mode} provider={t.meta.provider} model={t.meta.model} fallback={t.meta.fallback_reason} latency={t.meta.latency_ms} />
                <Trace steps={t.meta.steps} />
              </>
            )}
          </div>
        ))}
        {ask.isPending && <div className="msg"><span className="muted">Looking that up…</span></div>}
        {ask.isError && <ErrorBox error={ask.error} />}
        {followUps.length > 0 && (
          <div className="chips" aria-label="Suggested questions">
            {followUps.map((q) => <button key={q} className="chip" onClick={() => send(q)} disabled={ask.isPending}>{q}</button>)}
          </div>
        )}
        <div ref={end} />
      </div>
      <form className="composer" onSubmit={(e) => { e.preventDefault(); send(text) }}>
        <label htmlFor="q" className="sr-only">Your question</label>
        <input id="q" className="input" value={text} maxLength={500} placeholder="e.g. Which transformers have the most unmetered energy?"
          onChange={(e) => setText(e.target.value)} />
        <button className="btn btn-primary" disabled={text.trim().length < 3 || ask.isPending}>Ask</button>
        {turns.length > 0 && <button type="button" className="btn" onClick={() => { setTurns([]); ask.reset() }}>Clear</button>}
      </form>
    </>
  )
}
