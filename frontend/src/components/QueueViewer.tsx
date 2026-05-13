/**
 * QueueViewer Component
 * 
 * Displays prioritized inspection queue
 */

import { useState, useEffect, useCallback } from 'react'
import './QueueViewer.css'
import { API_BASE } from '../api'

interface QueueItem {
  rank: number
  meter_id: string
  dt_id: string
  feeder_id: string
  zone: string | null
  confidence: number
  estimated_inr_lost: number | null
  anomaly_type: string
  description: string
  status: string
}

function QueueViewer() {
  const [items, setItems] = useState<QueueItem[]>([])
  const [loading, setLoading] = useState(true)

  const fetchQueue = useCallback(async () => {
    setLoading(true)
    try {
      const res = await fetch(`${API_BASE}/api/v1/queue/daily`)
      if (!res.ok) throw new Error('Failed to fetch queue')
      const data = await res.json()
      setItems(data.items || [])
    } catch (err) {
      console.error('Queue fetch error:', err)
      setItems([])
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    fetchQueue()
    window.addEventListener('queue-refresh', fetchQueue)
    return () => window.removeEventListener('queue-refresh', fetchQueue)
  }, [fetchQueue])

  if (loading) {
    return <div className="queue-viewer loading">Loading queue...</div>
  }

  const confidenceTier = (c: number) => {
    if (c >= 0.85) return { label: 'HIGH', cls: 'tier-high' }
    if (c >= 0.65) return { label: 'MEDIUM', cls: 'tier-medium' }
    if (c >= 0.50) return { label: 'REVIEW', cls: 'tier-review' }
    return { label: 'NORMAL', cls: 'tier-normal' }
  }

  return (
    <div className="queue-viewer">
      <h2>Inspection Queue</h2>
      <p className="queue-subtitle">Sorted by Rs. × confidence · {items.filter(i => i.status === 'pending').length} pending</p>
      <table className="queue-table">
        <thead>
          <tr>
            <th>Rank</th>
            <th>Meter</th>
            <th>Zone</th>
            <th>Type</th>
            <th>Confidence</th>
            <th>Tier</th>
            <th>Est. Loss</th>
            <th>Status</th>
          </tr>
        </thead>
        <tbody>
          {items.map(item => {
            const tier = confidenceTier(item.confidence)
            return (
              <tr key={item.meter_id}>
                <td>{item.rank}</td>
                <td>{item.meter_id}</td>
                <td>{item.zone || '-'}</td>
                <td>{item.anomaly_type}</td>
                <td>{(item.confidence * 100).toFixed(0)}%</td>
                <td><span className={`confidence-tier ${tier.cls}`}>{tier.label}</span></td>
                <td>{item.estimated_inr_lost != null ? `₹${item.estimated_inr_lost.toLocaleString('en-IN')}` : '-'}</td>
                <td>{item.status}</td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

export default QueueViewer
