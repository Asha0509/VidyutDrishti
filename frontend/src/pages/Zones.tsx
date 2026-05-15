import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { CircleMarker, MapContainer, TileLayer, Tooltip as MapTip } from 'react-leaflet'
import 'leaflet/dist/leaflet.css'
import { Area, CartesianGrid, ComposedChart, Line, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { get } from '../api'
import DTDiagram from '../components/DTDiagram'
import { ChartTip, ErrorBox, Loading, PageHead, TierTag } from '../components/ui'
import { inr } from '../lib/format'
import { latestBalance, useBalance, useMeters, useZones } from '../lib/queries'
import type { Zone } from '../lib/types'

const RISK_COLOR: Record<string, string> = { HIGH: '#B42318', MEDIUM: '#B54708', REVIEW: '#475467', LOW: '#067647', NORMAL: '#067647' }

interface Forecast {
  feeder_id: string; peak_forecast_kw: number; source: string
  points: { timestamp: string; forecast_kw: number; lower_kw: number; upper_kw: number }[]
  history: { timestamp: string; kw: number }[]
}

const hhmm = (ts: string) => ts.slice(11, 16)

function ForecastCard({ zone }: { zone: Zone }) {
  const f = useQuery({ queryKey: ['forecast', zone.feeder_id], queryFn: () => get<Forecast>(`/forecast/${zone.feeder_id}`), retry: false })
  const data = f.data ? [
    ...f.data.history.map((h) => ({ t: h.timestamp, actual: h.kw })),
    ...f.data.points.filter((p) => p.timestamp > (f.data!.history[f.data!.history.length - 1]?.timestamp ?? '')).map((p) => ({ t: p.timestamp, forecast: p.forecast_kw, band: [p.lower_kw, p.upper_kw] as [number, number] })),
  ] : []
  return (
    <div className="card">
      <div className="card-head">
        <h3>Feeder {zone.feeder_id}: demand, last 24 h and next 24 h</h3>
        {f.data && <p>Forecast peak {f.data.peak_forecast_kw.toFixed(1)} kW</p>}
      </div>
      {f.isLoading && <Loading />}
      {f.isError && <ErrorBox error={f.error} />}
      {f.data && (
        <>
          <div className="legend">
            <span><i style={{ background: '#14917A' }} />Measured</span>
            <span><i style={{ background: '#2F6DB5' }} />Forecast</span>
            <span><i className="box" style={{ background: 'rgba(47,109,181,0.18)' }} />Likely range</span>
          </div>
          <div className="chart chart-sm">
            <ResponsiveContainer>
              <ComposedChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: -16 }}>
                <CartesianGrid stroke="#E3E8EE" vertical={false} />
                <XAxis dataKey="t" tickFormatter={hhmm} minTickGap={40} tick={{ fontSize: 12, fill: '#5d6b7c' }} tickLine={false} />
                <YAxis tick={{ fontSize: 12, fill: '#5d6b7c' }} tickLine={false} axisLine={false} width={48} />
                <Tooltip content={({ active, payload, label }) => active && payload?.length ? (
                  <ChartTip title={`${String(label).slice(0, 10)} ${hhmm(String(label))}`} rows={payload[0].payload.actual != null
                    ? [{ name: 'Measured', value: `${payload[0].payload.actual} kW`, color: '#14917A' }]
                    : [{ name: 'Forecast', value: `${payload[0].payload.forecast} kW`, color: '#2F6DB5' },
                       { name: 'Range', value: `${payload[0].payload.band[0].toFixed(1)}–${payload[0].payload.band[1].toFixed(1)} kW` }]} />) : null} />
                <Area dataKey="band" stroke="none" fill="rgba(47,109,181,0.18)" isAnimationActive={false} />
                <Line dataKey="actual" stroke="#14917A" strokeWidth={2} dot={false} isAnimationActive={false} />
                <Line dataKey="forecast" stroke="#2F6DB5" strokeWidth={2} dot={false} isAnimationActive={false} />
              </ComposedChart>
            </ResponsiveContainer>
          </div>
          <p className="small muted">{f.data.source}</p>
        </>
      )}
    </div>
  )
}

export default function Zones() {
  const zones = useZones()
  const meters = useMeters()
  const bal = useBalance(7)
  const [sel, setSel] = useState<string | null>(null)
  if (zones.isLoading) return <Loading />
  if (zones.isError) return <ErrorBox error={zones.error} retry={() => zones.refetch()} />
  const list = [...zones.data!].sort((a, b) => b.estimated_inr_lost - a.estimated_inr_lost)
  const latest = latestBalance(bal.data)
  const current = list.find((z) => z.id === sel) ?? list[0]

  return (
    <>
      <PageHead title="Zones & transformers"
        sub="Each zone is fed by one transformer. The diagram shows its meters coloured by risk and the share of energy that no meter recorded." />
      <div className="stack">
        <div className="grid grid-2">
          <div className="card">
            <div className="card-head"><h3>Where the risk is</h3><p>Circle size: estimated monthly loss</p></div>
            <div className="map">
              <MapContainer center={[12.95, 77.61]} zoom={11} scrollWheelZoom={false} style={{ height: '100%' }}>
                <TileLayer attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
                  url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png" />
                {list.map((z) => (
                  <CircleMarker key={z.id} center={[z.lat, z.lng]} radius={8 + Math.sqrt(z.estimated_inr_lost) / 18}
                    pathOptions={{ color: RISK_COLOR[z.risk], fillColor: RISK_COLOR[z.risk], fillOpacity: 0.35, weight: z.id === current.id ? 4 : 2 }}
                    eventHandlers={{ click: () => setSel(z.id) }}>
                    <MapTip>{z.place}: {z.flagged} flagged, {inr(z.estimated_inr_lost)}/month</MapTip>
                  </CircleMarker>
                ))}
              </MapContainer>
            </div>
          </div>
          <div className="card">
            <div className="card-head"><h3>Zones by estimated loss</h3></div>
            <div className="table-wrap">
              <table className="data">
                <thead><tr><th>Zone</th><th>Risk</th><th className="r">Flagged</th><th className="r">Unmetered</th><th className="r">₹ / month</th></tr></thead>
                <tbody>
                  {list.map((z) => (
                    <tr key={z.id} onClick={() => setSel(z.id)} style={{ cursor: 'pointer', background: z.id === current.id ? '#fff8e1' : undefined }}>
                      <td><button className="btn-ghost" style={{ border: 0, padding: 0, cursor: 'pointer', textAlign: 'left' }} onClick={() => setSel(z.id)}
                        aria-pressed={z.id === current.id}><b>{z.place}</b><div className="muted small">{z.id} · {z.dt_id}</div></button></td>
                      <td><TierTag tier={z.risk} /></td>
                      <td className="r">{z.flagged} / {z.meter_count}</td>
                      <td className="r">{latest[z.dt_id] ? `${latest[z.dt_id].unmetered_pct.toFixed(1)}%` : '–'}</td>
                      <td className="r">{inr(z.estimated_inr_lost)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </div>

        <div className="grid grid-2">
          <div className="card">
            <div className="card-head">
              <h3>{current.place} · {current.dt_id}</h3>
              <p>{current.pending_inspections} awaiting inspection</p>
            </div>
            {meters.data && (
              <DTDiagram dtId={current.dt_id} meters={meters.data.filter((m) => m.dt_id === current.dt_id)}
                kwhIn={latest[current.dt_id]?.kwh_in} unmeteredPct={latest[current.dt_id]?.unmetered_pct} />
            )}
            <p className="small muted">Select a meter for its evidence. <Link to={`/app/queue`}>Inspection queue</Link></p>
          </div>
          <ForecastCard zone={current} />
        </div>

        <div>
          <h3 style={{ marginBottom: '0.7rem' }}>All transformers</h3>
          <div className="grid grid-2">
            {list.map((z) => (
              <div className="card" key={z.id}>
                <div className="spread small" style={{ marginBottom: '0.4rem' }}><b>{z.place}</b><TierTag tier={z.risk} /></div>
                {meters.data && <DTDiagram dtId={z.dt_id} meters={meters.data.filter((m) => m.dt_id === z.dt_id)}
                  kwhIn={latest[z.dt_id]?.kwh_in} unmeteredPct={latest[z.dt_id]?.unmetered_pct} />}
              </div>
            ))}
          </div>
        </div>
      </div>
    </>
  )
}
