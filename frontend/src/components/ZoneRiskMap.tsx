/**
 * ZoneRiskMap Component
 *
 * DT-level risk heatmap using Leaflet.
 * Zones are derived from actual ingested meter topology — no hardcoded data.
 * Zones colored by risk: HIGH (red), MEDIUM (orange), LOW (green).
 */

import { useState, useEffect } from 'react'
import { MapContainer, TileLayer, CircleMarker, Popup } from 'react-leaflet'
import 'leaflet/dist/leaflet.css'
import './ZoneRiskMap.css'
import { API_BASE } from '../api'

interface ZoneData {
  id: string
  name: string
  dt_id: string
  feeder_id: string
  lat: number
  lng: number
  risk: 'HIGH' | 'MEDIUM' | 'LOW'
  risk_score: number
  meter_count: number
  total_kwh_today: number
  pending_inspections: number
  estimated_inr_lost: number
}

const RISK_COLORS: Record<string, string> = {
  HIGH: '#ef4444',
  MEDIUM: '#f59e0b',
  LOW: '#10b981',
}

function ZoneRiskMap() {
  const [selectedZone, setSelectedZone] = useState<ZoneData | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [zones, setZones] = useState<ZoneData[]>([])

  useEffect(() => {
    const fetchZones = async () => {
      try {
        const response = await fetch(`${API_BASE}/api/v1/zones/summary`)
        if (!response.ok) throw new Error(`HTTP ${response.status}`)
        const data = await response.json()
        setZones(data.zones)
      } catch (err) {
        console.error('Failed to fetch zone summary:', err)
        setError('Could not load zone data. Is the backend running?')
      } finally {
        setLoading(false)
      }
    }
    fetchZones()
  }, [])

  if (loading) {
    return <div className="zone-map loading">Loading zone risk map...</div>
  }

  if (error) {
    return <div className="zone-map loading">{error}</div>
  }

  if (zones.length === 0) {
    return <div className="zone-map loading">No zone data yet. Ingest meter readings first.</div>
  }

  return (
    <div className="zone-map">
      <h2>Zone Risk Map — Distribution Transformer Network</h2>

      <div className="map-legend">
        <div className="legend-item">
          <span className="legend-dot high" />
          <span>HIGH Risk (anomaly confidence &gt;65%)</span>
        </div>
        <div className="legend-item">
          <span className="legend-dot medium" />
          <span>MEDIUM Risk (35–65%)</span>
        </div>
        <div className="legend-item">
          <span className="legend-dot low" />
          <span>LOW Risk (&lt;35%)</span>
        </div>
      </div>

      <div className="map-container">
        <MapContainer
          center={[12.9716, 77.5946]}
          zoom={12}
          scrollWheelZoom={true}
          style={{ height: '500px', width: '100%', borderRadius: '8px' }}
        >
          <TileLayer
            attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
            url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
          />
          {zones.map((zone) => (
            <CircleMarker
              key={zone.id}
              center={[zone.lat, zone.lng]}
              radius={14 + zone.risk_score * 22}
              fillColor={RISK_COLORS[zone.risk] ?? '#6b7280'}
              color={RISK_COLORS[zone.risk] ?? '#6b7280'}
              fillOpacity={0.75}
              weight={2}
              eventHandlers={{ click: () => setSelectedZone(zone) }}
            >
              <Popup>
                <div className="zone-popup">
                  <h4>{zone.name} ({zone.dt_id})</h4>
                  <div className="popup-row">
                    <span className="popup-label">Risk Level:</span>
                    <span className={`popup-value ${zone.risk.toLowerCase()}`}>{zone.risk}</span>
                  </div>
                  <div className="popup-row">
                    <span className="popup-label">Feeder:</span>
                    <span className="popup-value">{zone.feeder_id}</span>
                  </div>
                  <div className="popup-row">
                    <span className="popup-label">Meters:</span>
                    <span className="popup-value">{zone.meter_count}</span>
                  </div>
                  <div className="popup-row">
                    <span className="popup-label">kWh Today:</span>
                    <span className="popup-value">{zone.total_kwh_today.toLocaleString()} kWh</span>
                  </div>
                  <div className="popup-row">
                    <span className="popup-label">Pending Inspections:</span>
                    <span className="popup-value highlight">{zone.pending_inspections}</span>
                  </div>
                  <div className="popup-row">
                    <span className="popup-label">Est. Loss:</span>
                    <span className="popup-value loss">₹{zone.estimated_inr_lost.toLocaleString()}</span>
                  </div>
                </div>
              </Popup>
            </CircleMarker>
          ))}
        </MapContainer>
      </div>

      {selectedZone && (
        <div className="zone-detail">
          <h3>Zone Detail: {selectedZone.name} ({selectedZone.dt_id})</h3>
          <div className="detail-grid">
            <div className="detail-card">
              <h4>Risk Score</h4>
              <div className={`detail-value ${selectedZone.risk.toLowerCase()}`}>
                {(selectedZone.risk_score * 100).toFixed(0)}%
              </div>
            </div>
            <div className="detail-card">
              <h4>Meters in Zone</h4>
              <div className="detail-value">{selectedZone.meter_count}</div>
            </div>
            <div className="detail-card">
              <h4>Pending Inspections</h4>
              <div className="detail-value">{selectedZone.pending_inspections}</div>
            </div>
            <div className="detail-card">
              <h4>Est. Revenue Loss</h4>
              <div className="detail-value loss">₹{selectedZone.estimated_inr_lost.toLocaleString()}</div>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

export default ZoneRiskMap
