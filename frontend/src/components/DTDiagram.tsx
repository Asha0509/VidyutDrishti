import { useNavigate } from 'react-router-dom'
import type { MeterSummary, Tier } from '../lib/types'

// Single-line diagram of one distribution transformer: energy comes in at the
// top, splits across the busbar to each customer meter, and whatever the
// meters don't record leaves through the amber "unmetered" branch.

const LIGHT: Record<Tier, { stroke: string; fill: string; text: string }> = {
  HIGH: { stroke: '#B42318', fill: '#FEF3F2', text: '#B42318' },
  MEDIUM: { stroke: '#B54708', fill: '#FFFAEB', text: '#B54708' },
  REVIEW: { stroke: '#475467', fill: '#F2F4F7', text: '#475467' },
  NORMAL: { stroke: '#8a97a6', fill: '#FFFFFF', text: '#3b4a5c' },
}
const DARK: Record<Tier, { stroke: string; fill: string; text: string }> = {
  HIGH: { stroke: '#F97066', fill: 'rgba(249,112,102,0.16)', text: '#FDA29B' },
  MEDIUM: { stroke: '#FDB022', fill: 'rgba(253,176,34,0.14)', text: '#FEC84B' },
  REVIEW: { stroke: '#98A2B3', fill: 'rgba(152,162,179,0.14)', text: '#D0D5DD' },
  NORMAL: { stroke: '#5d7088', fill: 'rgba(255,255,255,0.03)', text: '#c9d3de' },
}
const SHORT: Record<Tier, string> = { HIGH: 'HIGH', MEDIUM: 'MED', REVIEW: 'REVIEW', NORMAL: 'OK' }

interface Props {
  dtId: string
  meters: MeterSummary[]
  kwhIn?: number
  unmeteredPct?: number
  dark?: boolean
  linkable?: boolean
}

export default function DTDiagram({ dtId, meters, kwhIn, unmeteredPct, dark, linkable = true }: Props) {
  const nav = useNavigate()
  const pal = dark ? DARK : LIGHT
  const ink = dark ? '#dfe6ee' : '#142030'
  const sub = dark ? '#9fb0c2' : '#5d6b7c'
  const wire = dark ? '#6b7f96' : '#5d6b7c'
  const amber = dark ? '#F5B94A' : '#C27C0E'
  const list = [...meters].sort((a, b) => a.meter_id.localeCompare(b.meter_id))
  const n = Math.max(list.length, 1)
  const x0 = 92, x1 = 420
  const step = n > 1 ? (x1 - x0) / (n - 1) : 0
  const leakX = 486
  const share = Math.max(0, unmeteredPct ?? 0)
  const leakW = 2 + Math.min(share, 80) / 8
  const flagged = list.filter((m) => m.flagged).length

  return (
    <svg className="sld" viewBox="0 0 520 262" role="img"
      aria-label={`Transformer ${dtId}: ${list.length} meters, ${flagged} flagged` +
        (unmeteredPct != null ? `, ${unmeteredPct.toFixed(1)}% of incoming energy unmetered` : '')}>
      <style>{`
        .flow { stroke-dasharray: 7 9; animation: flow 1.4s linear infinite; }
        @keyframes flow { to { stroke-dashoffset: -16; } }
        @media (prefers-reduced-motion: reduce) { .flow { animation: none; } }
        .m-hit { cursor: ${linkable ? 'pointer' : 'default'}; }
        .m-hit:hover rect.box, .m-hit:focus rect.box { stroke-width: 3; }
      `}</style>
      {/* incoming feeder + transformer */}
      <line x1={56} y1={0} x2={56} y2={24} stroke={wire} strokeWidth={3} />
      <circle cx={56} cy={38} r={14} fill="none" stroke={ink} strokeWidth={2.5} />
      <circle cx={56} cy={56} r={14} fill="none" stroke={ink} strokeWidth={2.5} />
      <line x1={56} y1={70} x2={56} y2={118} stroke={wire} strokeWidth={3} />
      <text x={82} y={40} fill={ink} fontSize={19} fontWeight={700}>{dtId}</text>
      {kwhIn != null && <text x={82} y={62} fill={sub} fontSize={15}>{Math.round(kwhIn).toLocaleString('en-IN')} kWh in today</text>}

      {/* busbar */}
      <line x1={40} y1={118} x2={leakX} y2={118} stroke={wire} strokeWidth={4} strokeLinecap="round" />
      <line x1={40} y1={118} x2={leakX} y2={118} stroke={dark ? '#c9d3de' : '#ffffff'} strokeWidth={1.5} className="flow" opacity={0.7} />

      {list.map((m, i) => {
        const x = x0 + i * step
        const c = pal[m.tier]
        const label = m.meter_id.split('-')[1] ?? m.meter_id
        const go = () => linkable && nav(`/app/meters/${m.meter_id}`)
        return (
          <g key={m.meter_id} className="m-hit" onClick={go} tabIndex={linkable ? 0 : -1}
            onKeyDown={(e) => (e.key === 'Enter' || e.key === ' ') && go()}
            role={linkable ? 'link' : undefined}
            aria-label={`${m.meter_id}: ${m.tier.toLowerCase()} risk${m.flagged ? `, ${Math.round(m.drop_pct)}% below baseline` : ''}`}>
            <line x1={x} y1={118} x2={x} y2={156} stroke={wire} strokeWidth={2.5} />
            <rect className="box" x={x - 26} y={156} width={52} height={38} rx={4} fill={c.fill} stroke={c.stroke} strokeWidth={m.flagged ? 2.5 : 1.5} />
            <text x={x} y={181} textAnchor="middle" fill={ink} fontSize={16} fontWeight={600}>{label}</text>
            <text x={x} y={216} textAnchor="middle" fill={c.text} fontSize={14} fontWeight={700}>{SHORT[m.tier]}</text>
            {m.flagged && <text x={x} y={236} textAnchor="middle" fill={sub} fontSize={14}>−{Math.round(m.drop_pct)}%</text>}
          </g>
        )
      })}

      {/* unmetered branch */}
      {unmeteredPct != null && (
        <g aria-hidden="true">
          <line x1={leakX} y1={118} x2={leakX} y2={162} stroke={amber} strokeWidth={leakW} className="flow" />
          <path d={`M ${leakX - 14} 166 L ${leakX + 14} 166 L ${leakX} 188 Z`} fill={amber} />
          <text x={leakX} y={212} textAnchor="middle" fill={amber} fontSize={15} fontWeight={700}>{unmeteredPct.toFixed(0)}%</text>
          <text x={leakX} y={232} textAnchor="middle" fill={sub} fontSize={13}>unmetered</text>
        </g>
      )}
    </svg>
  )
}
