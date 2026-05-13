/**
 * ROI Calculator
 *
 * Interactive projection for BESCOM-scale deployment.
 * Lets the jury explore recovery scenarios based on detection rate,
 * average theft value, and current AT&C loss percentage.
 */

import { useEffect, useState } from 'react'
import './ROICalculator.css'
import { API_BASE } from '../api'

interface ROI {
  bescom_consumers: number
  current_atc_loss_pct: number
  detection_rate: number
  avg_monthly_theft_inr: number
  monthly_recovery_inr: number
  annual_recovery_inr: number
  inspector_cost_saved_pct: number
  payback_months: number
  five_year_npv_cr: number
}

function ROICalculator() {
  const [detectionRate, setDetectionRate] = useState(0.85)
  const [avgTheft, setAvgTheft] = useState(3500)
  const [atcLoss, setAtcLoss] = useState(17.0)
  const [roi, setRoi] = useState<ROI | null>(null)
  const [loading, setLoading] = useState(false)

  const fetchROI = async () => {
    setLoading(true)
    try {
      const params = new URLSearchParams({
        detection_rate: detectionRate.toString(),
        avg_monthly_theft_inr: avgTheft.toString(),
        atc_loss_pct: atcLoss.toString(),
      })
      const r = await fetch(`${API_BASE}/api/v1/metrics/roi?${params}`)
      const data = await r.json()
      setRoi(data)
    } catch (err) {
      console.error('ROI fetch error:', err)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    fetchROI()
  }, [detectionRate, avgTheft, atcLoss])

  const formatINR = (n: number) => {
    if (n >= 1e7) return `₹${(n / 1e7).toFixed(2)} Cr`
    if (n >= 1e5) return `₹${(n / 1e5).toFixed(2)} L`
    return `₹${n.toLocaleString('en-IN')}`
  }

  return (
    <div className="roi-container">
      <div className="roi-header">
        <h2>ROI Projection — BESCOM Scale</h2>
        <button 
          className="roi-refresh-btn" 
          onClick={fetchROI}
          disabled={loading}
        >
          {loading ? 'Refreshing...' : 'Refresh Data'}
        </button>
      </div>
      <p className="roi-subtitle">
        Interactive model for projected savings across ~8.5M consumers.
        Adjust the sliders to explore deployment scenarios.
      </p>

      <div className="roi-controls">
        <div className="roi-control">
          <label>
            Detection Rate: <strong>{(detectionRate * 100).toFixed(0)}%</strong>
          </label>
          <input
            type="range"
            min="0.5"
            max="1.0"
            step="0.05"
            value={detectionRate}
            onChange={(e) => setDetectionRate(parseFloat(e.target.value))}
          />
          <span className="roi-hint">Model recall on theft patterns</span>
        </div>

        <div className="roi-control">
          <label>
            Avg Monthly Theft: <strong>₹{avgTheft.toLocaleString('en-IN')}</strong>
          </label>
          <input
            type="range"
            min="1000"
            max="10000"
            step="500"
            value={avgTheft}
            onChange={(e) => setAvgTheft(parseInt(e.target.value))}
          />
          <span className="roi-hint">Per-connection revenue leakage</span>
        </div>

        <div className="roi-control">
          <label>
            Current AT&C Loss: <strong>{atcLoss.toFixed(1)}%</strong>
          </label>
          <input
            type="range"
            min="5"
            max="30"
            step="0.5"
            value={atcLoss}
            onChange={(e) => setAtcLoss(parseFloat(e.target.value))}
          />
          <span className="roi-hint">BESCOM baseline: ~17%</span>
        </div>
      </div>

      {loading && <div className="roi-loading">Computing…</div>}

      {roi && (
        <>
          <div className="roi-hero">
            <div className="roi-hero-item">
              <div className="roi-hero-value">{formatINR(roi.annual_recovery_inr)}</div>
              <div className="roi-hero-label">Projected Annual Recovery</div>
            </div>
            <div className="roi-hero-item">
              <div className="roi-hero-value">{roi.payback_months.toFixed(1)} mo</div>
              <div className="roi-hero-label">Platform Payback Period</div>
            </div>
            <div className="roi-hero-item">
              <div className="roi-hero-value">₹{roi.five_year_npv_cr.toFixed(0)} Cr</div>
              <div className="roi-hero-label">5-Year NPV (10% discount)</div>
            </div>
          </div>

          <div className="roi-breakdown">
            <h3>Assumptions & Breakdown</h3>
            <table className="roi-table">
              <tbody>
                <tr>
                  <td>Total BESCOM consumers</td>
                  <td>{roi.bescom_consumers.toLocaleString('en-IN')}</td>
                </tr>
                <tr>
                  <td>Estimated theft population (1.5%)</td>
                  <td>{Math.floor(roi.bescom_consumers * 0.015).toLocaleString('en-IN')}</td>
                </tr>
                <tr>
                  <td>Detected at {(roi.detection_rate * 100).toFixed(0)}% rate</td>
                  <td>
                    {Math.floor(roi.bescom_consumers * 0.015 * roi.detection_rate).toLocaleString(
                      'en-IN',
                    )}
                  </td>
                </tr>
                <tr>
                  <td>Monthly revenue recovered</td>
                  <td>{formatINR(roi.monthly_recovery_inr)}</td>
                </tr>
                <tr>
                  <td>Inspector cost savings (vs random)</td>
                  <td>{roi.inspector_cost_saved_pct.toFixed(0)}%</td>
                </tr>
                <tr>
                  <td>Annual platform cost (est.)</td>
                  <td>₹15 Cr</td>
                </tr>
              </tbody>
            </table>
          </div>

          <div className="roi-note">
            <strong>Methodology:</strong> Assumes 1.5% active-theft prevalence (conservative BESCOM
            estimate; industry range 1–3%), Rs. 6.50/unit tariff, and prioritised inspection queue
            reducing field labour by 65% vs random sampling. Platform cost includes infra + ops + 10 FTE support.
          </div>
        </>
      )}
    </div>
  )
}

export default ROICalculator
