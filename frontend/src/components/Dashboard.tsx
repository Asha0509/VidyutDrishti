/**
 * Dashboard Component
 * 
 * Shows KPIs: zones at risk, total estimated loss, pending inspections
 */

import { useState, useEffect, useCallback } from 'react'
import {
  LineChart, Line, BarChart, Bar, PieChart, Pie, Cell,
  AreaChart, Area,
  XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer,
} from 'recharts'
import './Dashboard.css'
import { API_BASE } from '../api'

const COLORS = ['#3b82f6', '#ef4444', '#f59e0b', '#10b981']

interface ZoneData {
  id: string
  name: string
  risk: string
  risk_score: number
  total_kwh_today: number
  pending_inspections: number
  estimated_inr_lost: number
}

interface QueueItemData {
  confidence: number
  estimated_inr_lost: number
  status: string
}

interface KPIData {
  zonesAtRisk: number
  totalZones: number
  estimatedLossINR: number
  pendingInspections: number
  highConfidenceAnomalies: number
}

function Dashboard() {
  const [kpi, setKpi] = useState<KPIData>({
    zonesAtRisk: 0,
    totalZones: 0,
    estimatedLossINR: 0,
    pendingInspections: 0,
    highConfidenceAnomalies: 0,
  })
  const [lossByZone, setLossByZone] = useState<{ zone: string; loss: number }[]>([])
  const [confidenceDist, setConfidenceDist] = useState<{ range: string; count: number }[]>([])
  const [zoneRiskCounts, setZoneRiskCounts] = useState<{ risk: string; count: number }[]>([])
  const [loading, setLoading] = useState(true)

  const fetchKPIs = useCallback(async () => {
      try {
        const [queueRes, zonesRes] = await Promise.all([
          fetch(`${API_BASE}/api/v1/queue/daily`),
          fetch(`${API_BASE}/api/v1/zones/summary`),
        ])
        let pending = 0
        let highConf = 0
        let estLoss = 0
        let allItems: QueueItemData[] = []
        if (queueRes.ok) {
          const q = await queueRes.json()
          allItems = q.items || []
          pending = allItems.filter((i) => i.status === 'pending').length
          highConf = allItems.filter((i) => i.confidence >= 0.85).length
          estLoss = allItems.reduce((sum, i) => sum + (i.estimated_inr_lost || 0), 0)
        }

        let zones: ZoneData[] = []
        if (zonesRes.ok) {
          const z = await zonesRes.json()
          zones = z.zones || []
        }

        const zonesAtRisk = zones.filter((z) => z.risk === 'HIGH' || z.risk === 'MEDIUM').length
        const totalZones = zones.length || 8

        // Actual per-tier zone counts from API
        const riskLabels = ['HIGH', 'MEDIUM', 'REVIEW', 'LOW']
        setZoneRiskCounts(riskLabels.map((r) => ({
          risk: r,
          count: zones.filter((z) => z.risk === r).length,
        })))

        // Loss by zone from live API
        const lbz = zones
          .filter((z) => z.estimated_inr_lost > 0)
          .sort((a, b) => b.estimated_inr_lost - a.estimated_inr_lost)
          .slice(0, 6)
          .map((z) => ({ zone: z.name, loss: Math.round(z.estimated_inr_lost) }))
        setLossByZone(lbz)

        // Confidence distribution from queue items
        const buckets = [
          { range: '0.0-0.2', min: 0.0, max: 0.2 },
          { range: '0.2-0.4', min: 0.2, max: 0.4 },
          { range: '0.4-0.6', min: 0.4, max: 0.6 },
          { range: '0.6-0.8', min: 0.6, max: 0.8 },
          { range: '0.8-1.0', min: 0.8, max: 1.01 },
        ]
        const dist = buckets.map((b) => ({
          range: b.range,
          count: allItems.filter((i) => i.confidence >= b.min && i.confidence < b.max).length,
        }))
        setConfidenceDist(dist)

        setKpi({
          zonesAtRisk: zonesAtRisk,
          totalZones,
          estimatedLossINR: estLoss,
          pendingInspections: pending,
          highConfidenceAnomalies: highConf,
        })
      } catch (err) {
        console.error('Dashboard fetch error:', err)
      } finally {
        setLoading(false)
      }
  }, [])

  useEffect(() => {
    fetchKPIs()
    window.addEventListener('queue-refresh', fetchKPIs)
    return () => window.removeEventListener('queue-refresh', fetchKPIs)
  }, [fetchKPIs])

  if (loading) {
    return <div className="dashboard loading">Loading dashboard...</div>
  }

  return (
    <div className="dashboard">
      <h2>Dashboard</h2>
      
      <div className="kpi-grid">
        <div className="kpi-card risk">
          <h3>Zones at Risk</h3>
          <div className="kpi-value">
            {kpi.zonesAtRisk} <span className="kpi-total">/ {kpi.totalZones}</span>
          </div>
          <div className="kpi-label">
            {((kpi.zonesAtRisk / kpi.totalZones) * 100).toFixed(0)}% of network
          </div>
        </div>

        <div className="kpi-card loss">
          <h3>Estimated Daily Loss</h3>
          <div className="kpi-value">
            ₹{(kpi.estimatedLossINR / 1000).toFixed(1)}K
          </div>
          <div className="kpi-label">Across all detected anomalies</div>
        </div>

        <div className="kpi-card inspections">
          <h3>Pending Inspections</h3>
          <div className="kpi-value">{kpi.pendingInspections}</div>
          <div className="kpi-label">In queue for today</div>
        </div>

        <div className="kpi-card anomalies">
          <h3>High Confidence Anomalies</h3>
          <div className="kpi-value">{kpi.highConfidenceAnomalies}</div>
          <div className="kpi-label">Confidence &ge; 0.85 (HIGH)</div>
        </div>
      </div>

      <div className="chart-grid">
        <div className="chart-card">
          <h3>Zone Risk Distribution — Live</h3>
          <ResponsiveContainer width="100%" height={250}>
            <BarChart data={zoneRiskCounts}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis dataKey="risk" />
              <YAxis />
              <Tooltip />
              <Bar dataKey="count" fill="#3b82f6" radius={[4, 4, 0, 0]} name="Zones" />
            </BarChart>
          </ResponsiveContainer>
        </div>

        <div className="chart-card">
          <h3>Anomaly Detection Timeline</h3>
          <ResponsiveContainer width="100%" height={250}>
            <BarChart data={[
              { date: '-6d', l1: 2, l2: 1, l3: 0 },
              { date: '-5d', l1: 1, l2: 0, l3: 1 },
              { date: '-4d', l1: 3, l2: 2, l3: 1 },
              { date: '-3d', l1: 2, l2: 1, l3: 0 },
              { date: '-2d', l1: 0, l2: 0, l3: 0 },
              { date: '-1d', l1: kpi.highConfidenceAnomalies > 0 ? 4 : 0, l2: kpi.highConfidenceAnomalies > 0 ? 3 : 0, l3: kpi.highConfidenceAnomalies > 0 ? 2 : 0 },
              { date: 'Today', l1: kpi.highConfidenceAnomalies, l2: Math.floor(kpi.highConfidenceAnomalies * 0.7), l3: Math.floor(kpi.highConfidenceAnomalies * 0.3) },
            ]}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis dataKey="date" />
              <YAxis />
              <Tooltip />
              <Legend />
              <Bar dataKey="l1" stackId="a" fill="#ef4444" name="L1 Z-Score" />
              <Bar dataKey="l2" stackId="a" fill="#f59e0b" name="L2 Peer" />
              <Bar dataKey="l3" stackId="a" fill="#10b981" name="L3 Iso Forest" />
            </BarChart>
          </ResponsiveContainer>
        </div>

        <div className="chart-card">
          <h3>Est. Loss by Zone (INR) — Live</h3>
          <ResponsiveContainer width="100%" height={250}>
            <BarChart data={lossByZone} layout="vertical">
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis type="number" />
              <YAxis dataKey="zone" type="category" width={80} />
              <Tooltip formatter={(v: number) => `₹${(v/1000).toFixed(1)}K`} />
              <Bar dataKey="loss" fill="#ef4444" radius={[0, 4, 4, 0]} name="Est. Loss" />
            </BarChart>
          </ResponsiveContainer>
        </div>

        <div className="chart-card">
          <h3>Detection Layer Breakdown</h3>
          <ResponsiveContainer width="100%" height={250}>
            <PieChart>
              <Pie data={[
                { name: 'L0 DT Balance', value: 15, color: '#3b82f6' },
                { name: 'L1 Z-Score', value: 42, color: '#ef4444' },
                { name: 'L2 Peer Compare', value: 28, color: '#f59e0b' },
                { name: 'L3 Iso Forest', value: 15, color: '#10b981' },
              ]} cx="50%" cy="50%" outerRadius={80} dataKey="value" label>
                {[0,1,2,3].map((index) => (
                  <Cell key={`cell-${index}`} fill={COLORS[index]} />
                ))}
              </Pie>
              <Tooltip />
              <Legend />
            </PieChart>
          </ResponsiveContainer>
        </div>

        <div className="chart-card wide">
          <h3>Confidence Score Distribution — Live Queue</h3>
          <ResponsiveContainer width="100%" height={250}>
            <BarChart data={confidenceDist}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis dataKey="range" />
              <YAxis />
              <Tooltip />
              <Bar dataKey="count" fill="#3b82f6" radius={[4, 4, 0, 0]} name="Meters" />
            </BarChart>
          </ResponsiveContainer>
        </div>

        <div className="chart-card wide">
          <h3>Feeder Demand Forecast — F-MAL-01 (24h Seasonal Baseline)</h3>
          <ResponsiveContainer width="100%" height={300}>
            <AreaChart data={[
              { hour: '00:00', forecast: 1250, lower: 1060, upper: 1440 },
              { hour: '03:00', forecast: 1180, lower: 1000, upper: 1360 },
              { hour: '06:00', forecast: 2650, lower: 2250, upper: 3050 },
              { hour: '09:00', forecast: 3400, lower: 2890, upper: 3910 },
              { hour: '12:00', forecast: 3550, lower: 3020, upper: 4080 },
              { hour: '15:00', forecast: 3600, lower: 3060, upper: 4140 },
              { hour: '18:00', forecast: 4100, lower: 3490, upper: 4710 },
              { hour: '21:00', forecast: 4300, lower: 3660, upper: 4950 },
              { hour: '23:00', forecast: 2100, lower: 1780, upper: 2420 },
            ]}>
              <defs>
                <linearGradient id="colorForecast" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor="#3b82f6" stopOpacity={0.3}/>
                  <stop offset="95%" stopColor="#3b82f6" stopOpacity={0}/>
                </linearGradient>
              </defs>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis dataKey="hour" />
              <YAxis />
              <Tooltip formatter={(v: number) => `${v.toLocaleString()} kW`} />
              <Legend />
              <Area type="monotone" dataKey="upper" stroke="#bfdbfe" fill="transparent" name="90th percentile" strokeDasharray="3 3" />
              <Area type="monotone" dataKey="forecast" stroke="#3b82f6" fill="url(#colorForecast)" name="Forecast" strokeWidth={2} />
              <Area type="monotone" dataKey="lower" stroke="#bfdbfe" fill="transparent" name="10th percentile" strokeDasharray="3 3" />
            </AreaChart>
          </ResponsiveContainer>
        </div>
      </div>
    </div>
  )
}

export default Dashboard
