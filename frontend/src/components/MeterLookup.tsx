/**
 * MeterLookup Component
 *
 * Search for meter and display status with reasoning derived from
 * the live anomaly-detection layer signals.
 */

import { useState } from 'react'
import './MeterLookup.css'
import { API_BASE } from '../api'

interface LayerSignals {
  l0_is_anomaly: boolean
  l1_is_anomaly: boolean
  l1_z_score: number | null
  l2_is_anomaly: boolean
  l2_deviation_pct: number | null
  l3_is_anomaly: boolean
}

interface MeterStatus {
  meter_id: string
  date: string
  confidence: number
  is_anomaly: boolean
  anomaly_type: string | null
  layer_signals: LayerSignals
}

type Verdict = {
  level: 'URGENT' | 'REVIEW' | 'NORMAL'
  label: string
  summary: string
  className: string
}

function classifyVerdict(s: MeterStatus): Verdict {
  const c = s.confidence
  const layers = s.layer_signals
  const flags = [layers.l0_is_anomaly, layers.l1_is_anomaly, layers.l2_is_anomaly, layers.l3_is_anomaly].filter(Boolean).length

  if (c >= 0.65 || flags >= 3) {
    return {
      level: 'URGENT',
      label: 'URGENT — Field inspection recommended',
      summary: `Confidence ${(c * 100).toFixed(0)}% with ${flags} of 4 detection layers triggered.`,
      className: 'urgent',
    }
  }
  if (c >= 0.2 || flags >= 1) {
    return {
      level: 'REVIEW',
      label: 'REVIEW — Suspicious pattern detected',
      summary: `Confidence ${(c * 100).toFixed(0)}%. ${flags} detection layer${flags === 1 ? '' : 's'} flagged this meter; manual review suggested.`,
      className: 'review',
    }
  }
  return {
    level: 'NORMAL',
    label: 'NORMAL — Within expected behavior',
    summary: `Confidence ${(c * 100).toFixed(0)}%. No detection layers triggered; consumption patterns match historical baseline and peer group.`,
    className: 'normal',
  }
}

function reasonForL0(layers: LayerSignals): string {
  return layers.l0_is_anomaly
    ? 'DT-level energy balance shows imbalance — metered consumption deviates significantly from grid input on this transformer.'
    : 'DT-level energy balance is within technical-loss tolerance (≤3%).'
}

function reasonForL1(layers: LayerSignals): string {
  const z = layers.l1_z_score
  if (z === null || z === undefined) {
    return 'Insufficient historical data to compute a z-score baseline.'
  }
  const zAbs = Math.abs(z)
  const direction = z < 0 ? 'below' : 'above'
  if (layers.l1_is_anomaly) {
    return `Today's consumption is ${zAbs.toFixed(2)} standard deviations ${direction} this meter's own historical mean — beyond the 2σ alert threshold.`
  }
  if (zAbs >= 1.0) {
    return `Today's consumption is ${zAbs.toFixed(2)}σ ${direction} the historical mean — elevated but still within the normal band.`
  }
  return `Today's consumption sits ${zAbs.toFixed(2)}σ ${direction} the historical mean — typical day-to-day variation.`
}

function reasonForL2(layers: LayerSignals): string {
  const dev = layers.l2_deviation_pct
  if (dev === null || dev === undefined) {
    return 'No peer comparison available (insufficient peers in same DT and consumer category).'
  }
  const devAbs = Math.abs(dev)
  const direction = dev < 0 ? 'below' : 'above'
  if (layers.l2_is_anomaly) {
    return `Consumption is ${devAbs.toFixed(1)}% ${direction} the average of similar meters in the same DT and category — outside ±1.5σ peer band.`
  }
  return `Consumption is ${devAbs.toFixed(1)}% ${direction} peer average — within the normal peer-group spread.`
}

function reasonForL3(layers: LayerSignals): string {
  return layers.l3_is_anomaly
    ? 'Multivariate pattern (Isolation Forest) flagged this meter as an outlier across kWh, voltage and power-factor jointly.'
    : 'Multivariate behavioral signature (kWh + voltage + PF) is consistent with normal operation.'
}

function MeterLookup() {
  const [meterId, setMeterId] = useState('')
  const [status, setStatus] = useState<MeterStatus | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const handleSearch = async () => {
    if (!meterId) return
    setLoading(true)
    setError(null)
    try {
      const res = await fetch(`${API_BASE}/api/v1/meters/${meterId.toUpperCase()}/status`)
      if (!res.ok) {
        setError(res.status === 404 ? 'Meter not found' : `Error: ${res.status}`)
        setStatus(null)
      } else {
        setStatus(await res.json())
      }
    } catch {
      setError('Network error')
      setStatus(null)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="meter-lookup">
      <h2>Meter Lookup</h2>

      <div className="search-box">
        <input
          type="text"
          value={meterId}
          onChange={(e) => setMeterId(e.target.value)}
          placeholder="Enter meter ID (e.g., DT1-M01)"
          onKeyPress={(e) => e.key === 'Enter' && handleSearch()}
        />
        <button onClick={handleSearch} disabled={loading}>
          {loading ? 'Searching...' : 'Search'}
        </button>
      </div>

      {error && <div className="error-message">{error}</div>}

      {status && <MeterVerdictPanel status={status} />}
    </div>
  )
}

function MeterVerdictPanel({ status }: { status: MeterStatus }) {
  const verdict = classifyVerdict(status)
  const layers = status.layer_signals
  const flags = [layers.l0_is_anomaly, layers.l1_is_anomaly, layers.l2_is_anomaly, layers.l3_is_anomaly].filter(Boolean).length

  const reasoningRows: { tag: string; text: string; flagged: boolean }[] = [
    { tag: 'L0 · DT Balance', text: reasonForL0(layers), flagged: layers.l0_is_anomaly },
    { tag: 'L1 · Self-history Z-score', text: reasonForL1(layers), flagged: layers.l1_is_anomaly },
    { tag: 'L2 · Peer comparison', text: reasonForL2(layers), flagged: layers.l2_is_anomaly },
    { tag: 'L3 · Multivariate', text: reasonForL3(layers), flagged: layers.l3_is_anomaly },
  ]

  const peerDev = layers.l2_deviation_pct
  const peerDevDisplay = peerDev !== null && peerDev !== undefined
    ? `${peerDev > 0 ? '+' : ''}${peerDev.toFixed(1)}%`
    : '—'

  return (
    <div className={`status-card ${verdict.className}`}>
      <div className="status-header">
        <h3>Meter: {status.meter_id}</h3>
        <span className="meter-date">As of {status.date}</span>
      </div>

      <div className={`verdict-badge verdict-${verdict.className}`}>
        {verdict.level === 'URGENT' && '🚨 '}
        {verdict.level === 'REVIEW' && '⚠️ '}
        {verdict.level === 'NORMAL' && '✅ '}
        {verdict.label}
      </div>

      <p className="verdict-summary">{verdict.summary}</p>

      {status.anomaly_type && (
        <p className="anomaly-type-line">
          <strong>Suspected pattern:</strong> {status.anomaly_type.replace(/_/g, ' ')}
        </p>
      )}

      <div className="reasoning-section">
        <h4>Why this verdict?</h4>
        <ul className="reasoning-list">
          {reasoningRows.map((row) => (
            <li key={row.tag} className={row.flagged ? 'reason-alert' : 'reason-ok'}>
              <span className="reason-tag">{row.tag}</span>
              <span className="reason-text">{row.text}</span>
            </li>
          ))}
        </ul>
      </div>

      <div className="metric-grid">
        <div className="metric">
          <span className="metric-label">Confidence</span>
          <span className="metric-value">{(status.confidence * 100).toFixed(0)}%</span>
        </div>
        <div className="metric">
          <span className="metric-label">Z-score</span>
          <span className="metric-value">
            {layers.l1_z_score !== null ? layers.l1_z_score.toFixed(2) : '—'}
          </span>
        </div>
        <div className="metric">
          <span className="metric-label">Peer deviation</span>
          <span className="metric-value">{peerDevDisplay}</span>
        </div>
        <div className="metric">
          <span className="metric-label">Layers triggered</span>
          <span className="metric-value">{flags} / 4</span>
        </div>
      </div>
    </div>
  )
}

export default MeterLookup
